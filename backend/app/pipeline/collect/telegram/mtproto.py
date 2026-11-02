"""Conversion PURE des messages lus par le Client API Telegram (MTProto).

Aucun reseau ici, et aucune dependance a Telethon : un message est lu par
simple acces d'attributs (duck typing), ce qui rend le module testable avec
des doublures. Le client reseau vit dans `mtproto_client.py`.

Ce que le Client API apporte par rapport a l'apercu web (`scraper.py`) :
jusqu'a `DEFAULT_MAX_MESSAGES` messages par canal au lieu d'environ 20, les
canaux dont l'apercu web est desactive, les groupes publics, les METADONNEES
des fichiers joints (nom, taille, type) et l'origine des transferts.

⚠️ FICHIERS : METADONNEES SEULEMENT, JAMAIS LE CONTENU. Le nom et la taille
d'une archive (« acme_sn_clients.zip, 4,2 Go ») sont la preuve publique
qu'une fuite est annoncee ; les telecharger reviendrait a entrer en
possession de donnees exfiltrees (regles 1 et 2, meme frontiere que
`link_health.py`). Ce module ne connait que `msg.file.name/size/mime_type`,
que Telethon expose sans rien telecharger.

⚠️ AUCUNE IDENTITE DE PERSONNE. Dans un GROUPE, un message est ecrit par un
utilisateur : son identifiant, son nom et son @ ne sont JAMAIS repris
(regle 1 : ne pas desanonymiser). Seule la signature d'un message de CANAL
(`post_author`, publiee par le canal lui-meme) est conservee. Pour un
transfert, seul l'identifiant d'un CANAL d'origine est garde, jamais celui
d'un utilisateur.

⚠️ LES COMPTEURS NE SONT PAS DU CONTENU. Vues et nombre de transferts
augmentent a chaque consultation : ils vont dans `source_meta`, jamais dans
le `content`, sinon la deduplication par `content_hash` ne reconnaitrait
jamais un message deja vu (piege ORION/KRYBIT). Le nom et la taille d'un
fichier, eux, sont stables et font partie de l'annonce : ils vont dans le
contenu, ou la detection (volume, domaine dans un nom d'archive) les voit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Une seule requete GetHistory rend jusqu'a 100 messages. Au-dela, chaque
# centaine est une requete de plus vers Telegram : la collecte reste une
# FRAICHEUR incrementale (2 passes par jour), pas un rattrapage d'historique
# -- meme doctrine que Dread (`DEFAULT_MAX_PAGES = 1`). Un canal qui publie
# plus de 100 messages entre deux passes perd l'excedent : a mesurer avant
# de relever la borne.
DEFAULT_MAX_MESSAGES = 100


@dataclass(frozen=True)
class AttachedFile:
    """Metadonnees d'un fichier joint -- jamais son contenu."""

    name: str | None
    size: int | None
    mime_type: str | None


@dataclass(frozen=True)
class MtprotoMessage:
    channel: str
    message_id: int
    text: str
    published_at: datetime | None = None
    # Signature d'un message de CANAL uniquement, jamais l'auteur d'un
    # message de groupe (voir docstring du module).
    author: str | None = None
    views: int | None = None
    forwards: int | None = None
    forwarded_from_channel_id: int | None = None
    files: tuple[AttachedFile, ...] = ()

    @property
    def url(self) -> str:
        return f"https://t.me/{self.channel}/{self.message_id}"


def _entier(valeur: Any) -> int | None:
    return valeur if isinstance(valeur, int) and not isinstance(valeur, bool) else None


def _texte(valeur: Any) -> str | None:
    return valeur if isinstance(valeur, str) and valeur.strip() else None


def _fichier(message: Any) -> AttachedFile | None:
    """Metadonnees du fichier joint, ou None.

    Une photo seule n'est pas un fichier annonce : Telethon lui donne une
    taille mais aucun nom ; on ne la garde que si elle porte au moins un nom
    ou un type autre qu'image (une archive, un document)."""
    fichier = getattr(message, "file", None)
    if fichier is None:
        return None
    nom = _texte(getattr(fichier, "name", None))
    mime = _texte(getattr(fichier, "mime_type", None))
    if nom is None and (mime is None or mime.startswith("image/")):
        return None
    return AttachedFile(
        name=nom, size=_entier(getattr(fichier, "size", None)), mime_type=mime
    )


def _canal_d_origine(message: Any) -> int | None:
    """Identifiant du CANAL d'ou le message a ete transfere, ou None.

    `fwd_from.from_id` vaut `PeerChannel(channel_id=...)` pour un canal et
    `PeerUser(user_id=...)` pour une personne : seul le premier est lu."""
    entete = getattr(message, "fwd_from", None)
    origine = getattr(entete, "from_id", None) if entete is not None else None
    return (
        _entier(getattr(origine, "channel_id", None)) if origine is not None else None
    )


def message_from_telethon(message: Any, channel: str) -> MtprotoMessage | None:
    """Convertit un message Telethon, ou None s'il n'a ni texte ni fichier
    (message de service : epinglage, changement de titre, arrivee d'un membre).
    """
    identifiant = _entier(getattr(message, "id", None))
    if identifiant is None:
        return None
    texte = getattr(message, "message", None) or ""
    fichier = _fichier(message)
    if not texte.strip() and fichier is None:
        return None
    date = getattr(message, "date", None)
    # `post` = message publie par le canal lui-meme : sa signature est
    # publique. Dans un groupe, `post` est faux et l'auteur est une personne.
    auteur = (
        _texte(getattr(message, "post_author", None))
        if getattr(message, "post", False)
        else None
    )
    return MtprotoMessage(
        channel=channel,
        message_id=identifiant,
        text=texte,
        published_at=date if isinstance(date, datetime) else None,
        author=auteur,
        views=_entier(getattr(message, "views", None)),
        forwards=_entier(getattr(message, "forwards", None)),
        forwarded_from_channel_id=_canal_d_origine(message),
        files=(fichier,) if fichier is not None else (),
    )


def human_size(octets: int | None) -> str | None:
    """Taille lisible, en unites binaires ecrites comme les annonces
    (« 4.2 GB ») pour que le detecteur de volume la reconnaisse."""
    if octets is None or octets < 0:
        return None
    valeur = float(octets)
    for unite in ("B", "KB", "MB", "GB", "TB"):
        if valeur < 1024 or unite == "TB":
            return f"{valeur:.0f} {unite}" if unite == "B" else f"{valeur:.1f} {unite}"
        valeur /= 1024
    return None  # pragma: no cover - inatteignable


def document_content(message: MtprotoMessage) -> str:
    """Contenu du document : le texte, puis une ligne par fichier joint.

    Uniquement des elements STABLES (voir docstring du module)."""
    lignes = [message.text.strip()] if message.text.strip() else []
    for f in message.files:
        details = ", ".join(x for x in (human_size(f.size), f.mime_type) if x)
        nom = f.name or "(sans nom)"
        lignes.append(f"Fichier joint : {nom}" + (f" ({details})" if details else ""))
    return "\n".join(lignes)


def document_title(message: MtprotoMessage, longueur_max: int = 120) -> str | None:
    """Premiere ligne du texte, ou a defaut le nom du fichier joint."""
    if message.text.strip():
        return message.text.strip().splitlines()[0][:longueur_max] or None
    for f in message.files:
        if f.name:
            return f.name[:longueur_max]
    return None


def document_meta(message: MtprotoMessage) -> dict[str, Any]:
    """`source_meta` : compteurs volatils et structure, hors `content`."""
    meta: dict[str, Any] = {
        "channel": message.channel,
        "message_id": message.message_id,
        "via": "mtproto",
        "views": message.views,
        "forwards": message.forwards,
    }
    if message.forwarded_from_channel_id is not None:
        meta["forwarded_from_channel_id"] = message.forwarded_from_channel_id
    if message.files:
        meta["files"] = [
            {"name": f.name, "size": f.size, "mime_type": f.mime_type}
            for f in message.files
        ]
    return meta
