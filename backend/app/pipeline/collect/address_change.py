"""Repérer qu'une source a changé d'adresse, et décider si l'on bascule
(2026-10-05). Logique pure, testable sans réseau.

Deux origines :
- LE SITE LUI-MÊME : un avis de migration servi à la place du contenu
  (DRAGON FORCE, « Migration completed », signé PGP), ou une annonce publiée
  dans le flux (LockBit : « new blog domain lockbit 5.0 ») ;
- LA LISTE deepdarkCTI (fastfire/deepdarkCTI, `forum.md` et
  `ransomware_gang.md`) : chaque nom y porte plusieurs adresses avec un statut
  ONLINE/OFFLINE. Le signal utile est « notre adresse n'est plus ONLINE, une
  autre du même nom l'est ».

⚠️ UNE ADRESSE ANNONCÉE N'EST PAS UNE PREUVE. L'annonce de LockBit pointe vers
un AUTRE site (LockBit 5), pas vers le même déménagé ; une liste communautaire
peut se tromper ; un avis de migration peut être un leurre. On ne bascule donc
automatiquement que si la nouvelle adresse PUBLIE LES MÊMES VICTIMES que
celles que nous connaissons déjà pour cette source, lues par le même parser
dédié. Sinon la candidate reste « à examiner » : c'est une décision
d'analyste.

⚠️ Les forums ne basculent jamais seuls : deux miroirs d'un forum n'exposent
pas forcément le même chemin de flux (DARKNET ARMY : HTTP 200, 0 contenu sur
la nouvelle adresse avec l'ancien chemin). Une bascule silencieuse ferait
retomber la source sur le collecteur générique sans erreur.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

# Adresse .onion v3 (56 caractères base32).
_ONION = re.compile(r"\b([a-z2-7]{56}\.onion)\b", re.IGNORECASE)

# Formules d'un déménagement. Volontairement EXPLICITES : « mirror » seul
# figure sur des pages qui listent leurs miroirs sans avoir bougé.
MIGRATION_MARKERS: tuple[str, ...] = (
    "migration completed",
    "we have moved",
    "we moved",
    "has moved",
    "moved to",
    "new address",
    "new domain",
    "new blog domain",
    "new onion",
    "new link",
    "our new",
    "nouvelle adresse",
    "nouveau domaine",
)

# Au-delà, une page qui mentionne un déménagement porte aussi du contenu.
_AVIS_COURT = 25_000

# Seuils de la preuve « même site ».
MIN_VICTIMES_LUES = 3
MIN_VICTIMES_COMMUNES = 3

APPLIED = "applied"
PENDING = "pending"
REJECTED = "rejected"


def host_of(url: str | None) -> str:
    """Hôte en minuscules, sans port, que l'URL ait un schéma ou non."""
    texte = (url or "").strip()
    if "//" not in texte:
        texte = "http://" + texte
    return (urlparse(texte).hostname or "").lower()


def onions_in(texte: str | None) -> list[str]:
    """Adresses .onion v3 citées, dans l'ordre, sans doublon."""
    vues: list[str] = []
    for m in _ONION.finditer(texte or ""):
        hote = m.group(1).lower()
        if hote not in vues:
            vues.append(hote)
    return vues


def _annonce_un_demenagement(texte: str) -> bool:
    bas = texte.lower()
    return any(m in bas for m in MIGRATION_MARKERS)


# Distance maximale (en caractères) entre une formule de déménagement et
# l'adresse annoncée. Mesure du 2026-10-05 : la page LockBit cite aussi
# l'adresse .onion officielle de Twitter, sans rapport avec un déménagement.
_PROXIMITE = 400


def announced_in_page(html: str | None, known_hosts: Iterable[str]) -> list[str]:
    """Adresses annoncées par une page qui SE DIT déménagée, et seulement
    celles qui figurent PRÈS d'une formule de déménagement. Une page sans
    formule ne propose rien, même si elle cite des .onion (liste de miroirs,
    liens vers d'autres services)."""
    if not html:
        return []
    bas = html.lower()
    positions = [
        i
        for m in MIGRATION_MARKERS
        for i in (j.start() for j in re.finditer(re.escape(m), bas))
    ]
    if not positions:
        return []
    connus = {h.lower() for h in known_hosts}
    retenues: list[str] = []
    for m in _ONION.finditer(html):
        hote = m.group(1).lower()
        if hote in connus or hote in retenues:
            continue
        if any(abs(m.start() - p) <= _PROXIMITE for p in positions):
            retenues.append(hote)
    return retenues


@dataclass(frozen=True)
class Annonce:
    host: str
    evidence: str


def announced_in_documents(
    documents: Iterable[tuple[str | None, str | None]],
    known_hosts: Iterable[str],
) -> list[Annonce]:
    """Annonces de nouvelle adresse dans les documents collectés de la source
    (titre, contenu). Cas réel : LockBit a publié « new blog domain lockbit
    5.0 » dans son propre flux ; nous l'avions collecté sans en rien tirer."""
    connus = {h.lower() for h in known_hosts}
    trouvees: dict[str, Annonce] = {}
    for titre, contenu in documents:
        texte = f"{titre or ''}\n{(contenu or '')[:4000]}"
        if not _annonce_un_demenagement(texte):
            continue
        for hote in onions_in(texte):
            if hote not in connus and hote not in trouvees:
                trouvees[hote] = Annonce(hote, (titre or "").strip()[:200])
    return list(trouvees.values())


# --------------------------------------------------------------------------
# deepdarkCTI
# --------------------------------------------------------------------------

# `| [Nom](url) | STATUT | ...` — espaces tolérés (format amont, 2026-08-22).
_LIGNE = re.compile(
    r"^\|\s*\[(?P<name>[^\]]+)\]\(\s*(?P<url>[^)\s]+)\s*\)\s*\|\s*(?P<status>[^|]*)\|"
)


@dataclass(frozen=True)
class ListEntry:
    name: str
    url: str
    status: str  # "ONLINE", "OFFLINE", "" ...


def parse_deepdarkcti(markdown: str) -> list[ListEntry]:
    entrees: list[ListEntry] = []
    for ligne in (markdown or "").splitlines():
        m = _LIGNE.match(ligne.strip())
        if not m or ".onion" not in m.group("url"):
            continue
        url = m.group("url").strip()
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        entrees.append(
            ListEntry(m.group("name").strip(), url, m.group("status").strip().upper())
        )
    return entrees


def name_key(name: str | None) -> str:
    """Clé de rapprochement d'un nom : avant la première parenthèse, sans
    accents ni ponctuation. « LOCKBIT 3.0 (New Dark mirror 1) (DLS) » et
    « LOCKBIT 3.0 (mirror 3) » donnent la même clé ; nos noms de source ont été
    créés à partir de ces listes."""
    base = (name or "").split("(")[0]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", base.lower())


@dataclass(frozen=True)
class ListVerdict:
    our_status: str | None  # statut de notre adresse dans la liste, None = absente
    candidates: list[ListEntry]


def compare_with_list(
    entries: list[ListEntry], source_name: str, known_hosts: Iterable[str]
) -> ListVerdict:
    """Statut de notre adresse dans la liste, et adresses ONLINE du même nom
    que nous ne connaissons pas."""
    cle = name_key(source_name)
    connus = {h.lower() for h in known_hosts}
    memes = [e for e in entries if cle and name_key(e.name) == cle]
    statuts = [e.status for e in memes if host_of(e.url) in connus]
    notre = "ONLINE" if "ONLINE" in statuts else (statuts[0] if statuts else None)
    candidates: list[ListEntry] = []
    for e in memes:
        if e.status == "ONLINE" and host_of(e.url) not in connus:
            if host_of(e.url) not in {host_of(c.url) for c in candidates}:
                candidates.append(e)
    return ListVerdict(notre, candidates)


def list_suggests_move(verdict: ListVerdict, stale: bool) -> bool:
    """Faut-il examiner les autres adresses ? Seulement si la nôtre n'est plus
    donnée ONLINE, ou si notre collecte ne réussit plus. Sinon on ne touche à
    rien : LockBit compte 26 adresses dans la liste, toutes « ONLINE »."""
    if not verdict.candidates:
        return False
    return verdict.our_status != "ONLINE" or stale


# --------------------------------------------------------------------------
# Décision
# --------------------------------------------------------------------------


def victim_key(name: str | None) -> str:
    base = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    base = re.sub(r"^https?://", "", base.lower()).removeprefix("www.")
    return re.sub(r"[^a-z0-9]", "", base)


def common_victims(lues: Iterable[str], connues: Iterable[str]) -> int:
    connus = {victim_key(v) for v in connues if victim_key(v)}
    return len({victim_key(v) for v in lues if victim_key(v)} & connus)


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str


def current_still_works(html: str | None, victimes_lues: int | None) -> bool:
    """L'adresse actuelle fonctionne-t-elle encore ? Une page vide, un avis de
    migration, ou (pour un site de fuite) aucune victime lisible = non.

    `victimes_lues=None` : pas de parser dédié, on ne juge que la page.

    ⚠️ Un site de fuite qui publie encore ses victimes FONCTIONNE, même s'il
    affiche un bandeau « new domain » (LockBit 3, mesuré le 2026-10-05 : 508
    victimes sous un bandeau annonçant LockBit 5). Seul un avis de migration
    COURT, sans contenu, signe une adresse éteinte (DRAGON FORCE : 18,9 Ko)."""
    if not html or not html.strip():
        return False
    if victimes_lues is not None:
        return victimes_lues >= MIN_VICTIMES_LUES
    return not (_annonce_un_demenagement(html) and len(html) < _AVIS_COURT)


def decide(
    *,
    reachable: bool,
    dedicated_parser: bool,
    parsed: int,
    common: int,
    current_works: bool = False,
) -> Decision:
    """Basculer seulement sur PREUVE que c'est le même site, ET que l'adresse
    actuelle ne fonctionne plus.

    ⚠️ Le second critère n'est pas décoratif. Le marqueur de parser « lockbit »
    reconnaît aussi l'adresse de LockBit 5, annoncée dans le flux de LockBit 3 :
    quelques victimes republiées suffiraient à faire basculer une source qui
    publie toujours. Un déménagement, c'est l'ancienne adresse qui s'éteint."""
    if current_works:
        return Decision(
            PENDING,
            "L'adresse actuelle fonctionne encore : miroir ou nouveau site du même "
            "groupe, pas un déménagement. À examiner.",
        )
    if not reachable:
        return Decision(PENDING, "Adresse injoignable via Tor à la vérification.")
    if not dedicated_parser:
        return Decision(
            PENDING,
            "Pas de bascule automatique : collecteur de forum ou générique, le "
            "chemin du flux peut différer d'un miroir à l'autre. À vérifier.",
        )
    if parsed < MIN_VICTIMES_LUES:
        return Decision(
            PENDING,
            f"La nouvelle adresse répond mais notre parser n'y lit que {parsed} "
            "victime(s) : site différent, ou structure modifiée.",
        )
    if common < MIN_VICTIMES_COMMUNES:
        return Decision(
            PENDING,
            f"{parsed} victimes lues, {common} déjà connues : probablement un AUTRE "
            "site du même groupe (nouvelle version), pas un déménagement.",
        )
    return Decision(
        APPLIED,
        f"Même site : {common} des {parsed} victimes lues sont déjà connues pour "
        "cette source.",
    )


def moved_url(old_url: str, new_host: str) -> str:
    """Nouvelle URL : même schéma et même chemin, nouvel hôte."""
    ancien = urlparse(old_url if "//" in old_url else "http://" + old_url)
    return ancien._replace(netloc=new_host).geturl()
