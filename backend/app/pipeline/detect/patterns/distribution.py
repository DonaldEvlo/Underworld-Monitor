"""Detection des canaux de distribution utilises pour diffuser une fuite
(hebergeur de fichiers, messagerie, paste site). Logique pure (voir CONTRIBUTING.md).

Meme principe que patterns/victim.py : exploiter ce que la collecte capture
deja de facon structuree plutot que de le re-deviner. Les collecteurs extraient
les liens sortants d'une annonce dans `source_meta["mentioned_urls"]` (voir
pipeline/collect/link_extraction.py, partage par tous les adaptateurs) -- 1193
URLs deja en base au moment de l'ecriture, jamais analysees jusqu'ici parce que
`detect_all` ne recoit que `content`, pas les metadonnees du document.

Ce que ce detecteur apporte a l'analyste : savoir OU la donnee volee est mise a
disposition (catbox.moe, qu.ax, mega.nz, Telegram...), signal operationnel
direct pour une demande de retrait ou une surveillance ciblee. C'est une
information d'infrastructure, distincte de DOMAIN (qui capte tout domaine
mentionne, y compris la victime ou une source d'actualite).

**Jamais l'URL complete, uniquement l'hote** : le chemin d'une URL de fuite
designe frequemment la victime elle-meme (constate en base :
`doxbin.net/upload/<nom-de-personne>`), ce serait de la PII. `value_masked` ne
porte donc que le nom d'hote, une donnee publique d'infrastructure -- coherent
avec la regle non negociable CONTRIBUTING.md §2.

Liste blanche d'hebergeurs plutot que detection ouverte : sur un corpus de
forums, les liens sortants sont majoritairement du bruit (reseaux sociaux,
pages d'accueil, redirections). Seuls les hotes dont la fonction est
d'heberger ou de transmettre un fichier sont retenus -- meme raisonnement que
la _TLD_ALLOWLIST de patterns/domain.py : une liste noire serait un jeu du chat
et de la souris sans fin. A completer quand un nouvel hebergeur apparait dans
le corpus reel."""

from __future__ import annotations

import re

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.raw_match import RawMatch

# Hebergeurs de fichiers / services de partage servant a diffuser des donnees
# volees. Constate empiriquement sur le corpus (catbox 86 mentions, qu.ax 52,
# offshore.cat 31, t.me 35) ou largement documente dans l'ecosysteme.
_FILE_HOSTS = {
    "anonfiles.com",
    "bayfiles.com",
    "catbox.moe",
    "files.catbox.moe",
    "gofile.io",
    "krakenfiles.com",
    "mediafire.com",
    "mega.nz",
    "mega.io",
    "offshore.cat",
    "files.offshore.cat",
    "pixeldrain.com",
    "qu.ax",
    "send.now",
    "temp.sh",
    "transfer.sh",
    "uploadfiles.io",
    "workupload.com",
    "zippyshare.com",
}

# Paste sites / plateformes de publication de contenu brut.
_PASTE_HOSTS = {
    "controlc.com",
    "doxbin.net",
    "doxbin.org",
    "ghostbin.com",
    "justpaste.it",
    "pastebin.com",
    "privatebin.net",
    "rentry.co",
    "telegra.ph",
}

# Messageries utilisees comme canal de diffusion (lien d'invitation vers un
# canal ou un bot qui distribue la donnee).
_MESSAGING_HOSTS = {
    "discord.com",
    "discord.gg",
    "t.me",
    "telegram.me",
}

_KNOWN_HOSTS = _FILE_HOSTS | _PASTE_HOSTS | _MESSAGING_HOSTS

_HOST_RE = re.compile(r"^[a-z0-9.-]+$")


def _host_of(url: str) -> str | None:
    """Nom d'hote d'une URL, sans le port ni le prefixe `www.`. Volontairement
    simple (pas d'urlparse) : l'entree vient de link_extraction, deja normalisee
    -- une forme inattendue doit etre ignoree, jamais provoquer d'erreur."""
    match = re.match(r"^\s*[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)", url.strip())
    if not match:
        return None
    host = match.group(1).split("@")[-1].split(":")[0].lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host if host and _HOST_RE.match(host) else None


def _registrable_suffix(host: str) -> str:
    """Deux derniers labels d'un hote ("files.catbox.moe" -> "catbox.moe"),
    pour reconnaitre un hebergeur quel que soit son sous-domaine. Comparaison
    par labels, jamais par sous-chaine (voir CONTRIBUTING.md §8)."""
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def find_distribution_channels(urls: list[str]) -> list[RawMatch]:
    """Retourne les canaux de distribution connus parmi `urls` (typiquement
    `source_meta["mentioned_urls"]` d'un document, voir registry.detect_all).

    Prend une liste d'URLs et non du texte libre : cette information est deja
    extraite et structuree par la couche collect, la re-parser depuis `content`
    reviendrait a refaire moins bien un travail deja fait."""
    matches = []
    seen: set[str] = set()

    for url in urls:
        if not isinstance(url, str):
            continue
        host = _host_of(url)
        if host is None:
            continue
        if host not in _KNOWN_HOSTS and _registrable_suffix(host) not in _KNOWN_HOSTS:
            continue
        if host in seen:
            continue
        seen.add(host)
        matches.append(
            RawMatch(
                type=DetectionType.DISTRIBUTION_CHANNEL,
                value_masked=host,
                value_hash=hash_value(host),
                # L'hote figure dans une liste connue d'hebergeurs : ce n'est
                # pas une inference, d'ou validated=True (meme logique que
                # patterns/victim.py).
                validated=True,
            )
        )

    return matches
