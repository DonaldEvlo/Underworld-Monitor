"""Corroboration d'une detection ou d'une alerte par l'agregateur RansomLook.

**Pourquoi ce module existe.** Nos collecteurs DLS vont directement au site
du gang : ils sont la source primaire. RansomLook, lui, surveille **77
groupes** la ou nous avons 6 collecteurs dedies. Le croisement repond donc a
une question que ni l'un ni l'autre ne tranche seul : *cette victime est-elle
vue par un second observateur independant ?*

Mesure du 2026-08-26 qui justifie l'approche : sur son flux de 1183 annonces,
**31 dataient de moins de 6 h** (la plus recente de 42 minutes) -- il n'est
donc PAS en retard sur notre collecte (2x/jour). L'objection intuitive
« clearnet = deja public, donc trop tard » est mesuree et fausse.

**Ce que la corroboration apporte concretement :**
  - `CORROBORATED` : un second observateur confirme. L'annonce n'est pas un
    artefact de parsing de notre cote, et le gang attribue est verifiable.
  - `EXCLUSIVE` : nous seuls voyons cette victime. Ce n'est PAS un signal de
    faiblesse -- c'est souvent l'inverse (nous lisons le DLS a la source,
    RansomLook ne l'a pas encore indexe). A ne jamais presenter comme un
    doute sur la detection.
  - `UNKNOWN` : le flux n'a pas pu etre recupere. Un echec reseau ne doit
    jamais degrader une alerte existante en « non corrobore » (voir plus bas).

**Regle 2 (jamais de PII) -- pourquoi c'est licite ici.** On ne corrobore que
des detections de type DOMAIN. `mask_domain` (pipeline/detect/masking.py)
laisse un domaine clearnet **en clair**, precisement parce qu'un domaine
n'est pas une PII. Aucune valeur masquee n'est donc reconstituee, et aucun
email/credential n'est jamais transmis a un tiers. C'est la meme frontiere
que `intelx.py`, qui corrobore un domaine de selecteur, jamais une valeur
sensible detectee.

**OPSEC.** Appel clearnet depuis le reseau `backend`, comme les autres
enrichisseurs (crt.sh, IntelX -- voir CONTRIBUTING.md §2). RansomLook interroge
son propre index deja constitue : ce n'est pas une requete vers
l'infrastructure d'une victime, ni vers un DLS.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum

# ⚠️ Normalisation des raisons sociales REUTILISEE, pas reecrite : c'est celle
# du rattachement par mot-cle (formes juridiques, sigles pointes, accents).
# Deux definitions du meme fait finissent par diverger (CONTRIBUTING.md §6).
from app.pipeline.alerting.matching import _LONGUEUR_MIN_NOM, _normalize_org_name
from app.pipeline.collect.ransomlook.scraper import _parse_discovered
from app.pipeline.detect.announcement_filter import source_publishes_victims
from app.pipeline.detect.infrastructure import is_infrastructure_domain

logger = logging.getLogger(__name__)


class CorroborationStatus(str, Enum):
    """Etat de corroboration d'une detection ou d'une alerte."""

    CORROBORATED = "corroborated"
    EXCLUSIVE = "exclusive"
    UNKNOWN = "unknown"
    # La question n'a pas de sens : domaine d'infrastructure, domaine CITE sur
    # un forum (pas une revendication), `.onion`, ou document de RansomLook
    # lui-meme (il ne peut pas se confirmer). A distinguer de « jamais
    # confronte » (NULL / unknown), qui est une absence de mesure.
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class CorroborationMatch:
    """Une correspondance trouvee dans le flux RansomLook.

    `group_name` est le gang que RansomLook attribue a la victime -- c'est la
    valeur ajoutee principale : nos collecteurs DLS savent deja de quel site
    vient un document, mais pour une victime vue ailleurs (RANSOMLOOK
    couvrait 1008 victimes absentes de notre collecte), c'est la seule
    attribution disponible."""

    domain: str
    group_name: str
    post_title: str
    discovered_at: datetime | None

    @property
    def evidence_url(self) -> str | None:
        """Lien PUBLIC citable qui justifie la corroboration.

        L'API `/api/posts` ne renvoie que trois champs (`group_name`,
        `post_title`, `discovered`) -- aucune URL. Mais RansomLook expose une
        page par gang, `/group/<nom>`, et **la victime y figure** : verifie
        le 2026-08-26 sur `krybit` (partenaire-exemple, domaine-exemple,
        negoce-exemple, microfinance-exemple) et `safepay` (ferme-exemple,
        new-point), toutes presentes dans le HTML.

        C'est donc une preuve consultable par un tiers -- contrairement a
        notre propre URL .onion, qui exige Tor. Les deux sont
        complementaires : l'une prouve ce que NOUS avons lu, l'autre ce
        qu'un observateur independant publie."""
        if not self.group_name:
            return None
        slug = self.group_name.strip().lower().replace(" ", "%20")
        return f"https://www.ransomlook.io/group/{slug}"


# Preuve PAR VICTIME. RansomLook publie une capture d'ecran de l'annonce du
# gang pour chaque victime, exposee par `/api/group/<gang>`.
#
# ⚠️ Mesure du 2026-09-04 avant d'en dependre : sur `krybit`, **136 posts sur
# 136** portent un champ `screen`, et les URLs resolvent (HTTP 200,
# ~50 a 120 Ko). Ce n'est donc pas une hypothese sur le format d'un site.
#
# ⚠️ On ne stocke QUE l'URL. L'image n'est ni telechargee ni conservee : c'est
# la meme regle que `link_health.py`, verifier n'est pas rapatrier.
#
# ⚠️ Le champ `link` du meme payload N'EST PAS citable : il vaut
# « /blog/<hash>/ », un chemin sur le site .onion DU GANG (verifie -- le hash
# est identique a celui de nos propres documents KRYBIT), pas une page
# RansomLook.
_RANSOMLOOK_GROUP_API = "https://www.ransomlook.io/api/group/{gang}"


def parse_group_victim_evidence(payload) -> dict[str, str]:
    """Domaine normalise -> URL publique de la capture, depuis `/api/group/`.

    Le payload est une liste `[metadonnees_du_gang, posts]`. Fonction PURE :
    le reseau est fait par l'appelant, ce qui la rend testable sans appel.
    """
    if not isinstance(payload, list) or len(payload) < 2:
        return {}
    posts = payload[1]
    if not isinstance(posts, list):
        return {}
    preuves: dict[str, str] = {}
    for post in posts:
        if not isinstance(post, dict):
            continue
        capture = (post.get("screen") or "").strip()
        titre = (post.get("post_title") or "").strip()
        if not capture or not titre:
            continue
        for candidat in _domain_candidates(titre):
            preuves.setdefault(
                candidat, "https://www.ransomlook.io/" + capture.lstrip("/")
            )
    return preuves


def group_evidence_api_url(group_name: str) -> str:
    return _RANSOMLOOK_GROUP_API.format(
        gang=group_name.strip().lower().replace(" ", "%20")
    )


def _normalise_domain(value: str) -> str:
    """Normalise un domaine pour comparaison structurelle.

    Meme discipline que `pipeline/alerting/matching.py` : on compare des
    LABELS, jamais des sous-chaines. `www.` est retire car RansomLook et les
    DLS ne s'accordent pas dessus (KRYBIT publie `www.partenaire-exemple.co.za`,
    RansomLook `partenaire-exemple.co.za`) -- sans cela, la corroboration echouerait
    sur des victimes pourtant identiques (constate sur les 3 victimes
    africaines communes)."""
    normalized = (value or "").strip().lower().rstrip(".")
    if normalized.startswith("http://"):
        normalized = normalized[len("http://") :]
    elif normalized.startswith("https://"):
        normalized = normalized[len("https://") :]
    normalized = normalized.split("/")[0]
    if normalized.startswith("www."):
        normalized = normalized[len("www.") :]
    return normalized


def _domain_candidates(title: str) -> set[str]:
    """Extrait les domaines plausibles d'un titre d'annonce RansomLook.

    Deux formes coexistent dans son flux, verifiees le 2026-08-26 :
      - un domaine nu : `systemes-exemple.com`, `www.clinique-exemple.com.br` ;
      - une raison sociale : `Crowe`, `Advanced Engineering Consultants`.
    Seule la premiere est corroborable ici -- une raison sociale ne peut pas
    etre rattachee a une entite par `matching.py`, qui ne gere que
    DOMAIN/EMAIL (meme limite structurelle que SARCOMA/METAENCRYPTER).

    ⚠️ FORMES COMPOSEES (2026-09-28) : ransomware.live ecrit parfois
    PLUSIEURS domaines dans un champ -- `compagnie-aerienne.co.tz / compagnie-aerienne.com`,
    `www.a.com, www.b.com` -- ou un schema mal forme (`https//…`, `hhtps://…`).
    Couper au premier `/` rendait `"compagnie-aerienne.co.tz "` (espace finale),
    rejete : Compagnie Aérienne Exemple, victime fraiche d'un secteur critique, restait sans
    renseignements, donc en gravite `medium` au lieu de `critical`. 7 champs
    sur 7 962 seulement, mais c'etait l'alerte phare. On decoupe desormais sur
    les separateurs EXPLICITES (` / `, `,`, `;`, `|`) et chaque morceau doit
    avoir la FORME d'un domaine (extension d'au moins 2 lettres) : sinon
    « EXEMPLO, S.A. DE C.V » donnerait un faux domaine `s.a`."""
    candidats: set[str] = set()
    for morceau in _SEPARATEURS.split(title or ""):
        morceau = _SCHEMA_MAL_FORME.sub("", morceau.strip())
        candidate = _normalise_domain(morceau)
        if _FORME_DOMAINE.fullmatch(candidate):
            candidats.add(candidate)
    return candidats


_SEPARATEURS = re.compile(r"\s+/\s+|\s*[,;|]\s*")
_SCHEMA_MAL_FORME = re.compile(r"^[a-z]{3,6}:?//", re.IGNORECASE)
_FORME_DOMAINE = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}")


def build_corroboration_index(
    posts: list,
) -> dict[str, CorroborationMatch]:
    """Indexe le flux RansomLook par domaine normalise.

    Construit UNE fois par passe puis interroge en memoire : corroborer N
    alertes ne doit pas declencher N appels reseau (le flux complet fait un
    seul appel, ~23 s).

    En cas de doublon (deux gangs revendiquant la meme victime, cas reel), on
    conserve l'annonce la PLUS RECENTE : c'est celle qui reflete l'etat
    courant de la revendication."""
    index: dict[str, CorroborationMatch] = {}
    for post in posts:
        title = getattr(post, "post_title", None) or ""
        group = getattr(post, "group_name", None) or ""
        # `RansomLookPost.discovered` est la chaine ISO brute rendue par
        # l'API ; on reutilise le parseur du collecteur plutot que d'en
        # ecrire un second qui divergerait.
        discovered = _parse_discovered(getattr(post, "discovered", None))
        for domain in _domain_candidates(title):
            existing = index.get(domain)
            if existing is not None:
                # Sans date des deux cotes, on garde le premier vu plutot que
                # d'ecraser arbitrairement.
                if discovered is None or existing.discovered_at is None:
                    continue
                if discovered <= existing.discovered_at:
                    continue
            index[domain] = CorroborationMatch(
                domain=domain,
                group_name=group,
                post_title=title,
                discovered_at=discovered,
            )
    return index


def corroborate_domain(
    domain: str, index: dict[str, CorroborationMatch]
) -> tuple[CorroborationStatus, CorroborationMatch | None]:
    """Corrobore UN domaine contre l'index RansomLook.

    Rapproche par labels : une victime publiee en `mail.acme.com` chez un
    gang et `acme.com` chez RansomLook designe la meme organisation. On
    n'utilise jamais `in` sur la chaine brute -- `not-acme.com` ne doit pas
    matcher `acme.com` (voir CONTRIBUTING.md §8)."""
    normalized = _normalise_domain(domain)
    if not normalized:
        return CorroborationStatus.EXCLUSIVE, None

    direct = index.get(normalized)
    if direct is not None:
        return CorroborationStatus.CORROBORATED, direct

    # Rapprochement par labels terminaux : `mail.acme.com` -> `acme.com`.
    labels = normalized.split(".")
    for start in range(1, len(labels) - 1):
        parent = ".".join(labels[start:])
        match = index.get(parent)
        if match is not None:
            return CorroborationStatus.CORROBORATED, match

    return CorroborationStatus.EXCLUSIVE, None


# ---------------------------------------------------------------------------
# Corroboration par VICTIME (2026-09-11)
# ---------------------------------------------------------------------------
#
# Mesures qui ont motive cette refonte (voir CONTRIBUTING.md §6) :
#   - le flux `/api/posts` ne couvre que ~30 jours : « exclusive » y voulait
#     surtout dire « hors fenetre », pas « vue par personne d'autre ».
#     Confrontees a l'HISTORIQUE COMPLET du gang, 95 % des victimes LOCKBIT
#     sont indexees par RansomLook -- 0 dans le flux ;
#   - la plupart des gangs publient des RAISONS SOCIALES, pas des domaines :
#     AKIRA 0 -> 93 %, NIGHT SPIRE 0 -> 98 %, QILIN 100 % par le nom ;
#   - 1442 « exclusive » etaient de l'infrastructure, et les domaines CITES
#     sur un forum recevaient le meme statut qu'une victime revendiquee ;
#   - l'index ne gardait qu'une annonce par domaine : une victime revendiquee
#     par deux gangs changeait d'attribution selon le jour.
#
# ⚠️ Ce que la corroboration prouve, et ce qu'elle ne prouve pas : RansomLook
# lit LE MEME site du gang que nous. Il confirme que l'annonce existe et que
# notre lecture est juste (pas un artefact de parsing) ; il ne confirme pas
# que la fuite est reelle.

# Observateurs tiers dont l'UNION forme la corroboration. Un nom d'observateur
# n'est PAS un gang : c'est qui a vu la victime.
OBSERVER_RANSOMLOOK = "ransomlook"
OBSERVER_RANSOMWARE_LIVE = "ransomware_live"

CORROBORABLE_TYPES = frozenset({"domain", "organization"})

# Nom de source -> identifiant du gang chez RansomLook, quand la regle
# generique (voir `gang_slug_for_source`) ne suffit pas.
_SLUG_OVERRIDES = {"lockbit30": "lockbit3"}


def normalise_gang(name: str | None) -> str:
    """Forme comparable d'un nom de gang : « Dragon Force » == « dragonforce »."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def gang_slug_for_source(source_name: str | None) -> str | None:
    """Identifiant RansomLook du gang dont une source est le site de fuite.

    « LOCKBIT 3.0 (New Dark mirror 1) (DLS) » -> `lockbit3` ;
    « MYDATA / ALPHA LOCKER (DLS) » -> `mydata`. Les parentheses decrivent
    notre collecte (miroir, type), pas le gang. Verifie le 2026-09-11 sur les
    17 sites de fuite en base : 15 identifiants existent chez RansomLook
    (APT73 et CMD n'y sont pas suivis)."""
    if not source_name:
        return None
    base = source_name.split("(")[0].split("/")[0]
    slug = normalise_gang(base)
    return _SLUG_OVERRIDES.get(slug, slug) or None


def is_corroborable(
    detection_type: str, value: str | None, collector: str | None
) -> bool:
    """La question « un tiers a-t-il vu cette victime ? » a-t-elle un sens ?

    Seulement pour une VICTIME : une detection domaine/raison sociale issue
    d'un document de site de fuite (un document = une victime), hors
    infrastructure. Un domaine cite sur un forum n'est la victime de
    personne ; un document RansomLook ne peut pas se confirmer lui-meme."""
    if detection_type not in CORROBORABLE_TYPES:
        return False
    collecteur = (collector or "").strip().lower()
    if collecteur == "ransomlook" or not source_publishes_victims(collecteur):
        return False
    valeur = (value or "").strip()
    if not valeur or "..." in valeur or valeur.lower().endswith(".onion"):
        return False
    if detection_type == "domain" and is_infrastructure_domain(valeur):
        return False
    return True


def domain_candidates(value: str | None) -> set[str]:
    """Domaine(s) normalise(s) portes par une valeur, vide si c'est un nom."""
    return _domain_candidates(value or "")


def name_key(value: str | None) -> str | None:
    """Cle de rapprochement d'une raison sociale, ou None (domaine, trop court).

    ⚠️ EGALITE apres normalisation, jamais inclusion : « Acme » ne rejoint
    ni « Acme County Sheriff » ni « Bank of Acme » (meme doctrine que le
    rattachement par mot-cle, CONTRIBUTING.md §6)."""
    if not value or _domain_candidates(value):
        return None
    cle = _normalize_org_name(value)
    return cle if len(cle) >= _LONGUEUR_MIN_NOM else None


@dataclass(frozen=True)
class Claim:
    """Une revendication vue par un observateur : un gang, une annonce, une date.

    ⚠️ `observers` porte QUI a vu cette victime (`ransomlook`, `ransomware_live`),
    pas le gang. Deux agregateurs qui lisent le meme DLS ne sont PAS
    independants (ils confirment que l'annonce existe et que notre lecture est
    juste, pas que la fuite est reelle) -- mais leur UNION augmente la
    couverture : ransomware.live suit des gangs que RansomLook ignore (APT73,
    CMD, PEAR : 0 % -> jusqu'a 94 % mesure le 2026-09-14)."""

    group_name: str
    post_title: str
    discovered_at: datetime | None
    # URL de la capture de l'annonce, quand l'observateur la fournit. On ne
    # stocke QUE l'URL, jamais l'image (meme regle que link_health.py).
    # ⚠️ Peut etre RELATIVE (RansomLook, `/screenshots/...`) ou ABSOLUE
    # (ransomware.live, `https://images.ransomware.live/...`).
    screenshot_path: str | None = None
    observers: frozenset[str] = frozenset({OBSERVER_RANSOMLOOK})

    @property
    def evidence_url(self) -> str | None:
        """Preuve publique citable : la capture propre a CETTE victime, sinon
        la page du gang (qui liste des centaines de victimes)."""
        if self.screenshot_path:
            if self.screenshot_path.startswith("http"):
                return self.screenshot_path
            return "https://www.ransomlook.io/" + self.screenshot_path.lstrip("/")
        if not self.group_name:
            return None
        slug = self.group_name.strip().lower().replace(" ", "%20")
        return f"https://www.ransomlook.io/group/{slug}"


def _plus_ancienne(a: Claim, b: Claim) -> Claim:
    if a.discovered_at is None:
        return b
    if b.discovered_at is None:
        return a
    return a if a.discovered_at <= b.discovered_at else b


def _ajouter(table: dict[str, list[Claim]], cle: str, claim: Claim) -> None:
    """Une revendication par GANG et par cle : la plus ancienne date, et la
    capture des qu'une des annonces en porte une."""
    claims = table.setdefault(cle, [])
    gang = normalise_gang(claim.group_name)
    for i, existante in enumerate(claims):
        if normalise_gang(existante.group_name) == gang:
            retenue = _plus_ancienne(existante, claim)
            capture = existante.screenshot_path or claim.screenshot_path
            # ⚠️ UNION des observateurs : la meme victime vue par RansomLook ET
            # ransomware.live est fusionnee en une revendication, mais les deux
            # observateurs sont conserves (c'est l'interet du second).
            claims[i] = replace(
                retenue,
                screenshot_path=capture,
                observers=existante.observers | claim.observers,
            )
            return
    claims.append(claim)


@dataclass
class VictimIndex:
    """Toutes les revendications connues, par domaine et par raison sociale.

    ⚠️ TOUTES, pas la plus recente : une victime revendiquee par deux gangs
    (cas reel : `transports-exemple.com`, NIGHT SPIRE et KRYBIT) est une
    information, pas un doublon a trancher arbitrairement."""

    by_domain: dict[str, list[Claim]] = field(default_factory=dict)
    by_name: dict[str, list[Claim]] = field(default_factory=dict)

    def add(
        self,
        group_name: str | None,
        post_title: str | None,
        discovered: datetime | str | None,
        screenshot_path: str | None = None,
        observer: str = OBSERVER_RANSOMLOOK,
    ) -> None:
        titre = (post_title or "").strip()
        gang = (group_name or "").strip()
        if not titre or not gang:
            return
        date = (
            discovered
            if isinstance(discovered, datetime)
            else _parse_discovered(discovered)
        )
        # ⚠️ Le flux `/api/posts` date avec fuseau, certains historiques de
        # gangs sans : les comparer levait TypeError (premiere passe reelle,
        # 2026-09-11). Une date sans fuseau est lue comme UTC.
        if date is not None and date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        claim = Claim(gang, titre, date, screenshot_path or None, frozenset({observer}))
        domaines = _domain_candidates(titre)
        for domaine in domaines:
            _ajouter(self.by_domain, domaine, claim)
        if not domaines:
            cle = name_key(titre)
            if cle:
                _ajouter(self.by_name, cle, claim)


def parse_group_history(payload) -> list[dict]:
    """Annonces de l'historique d'un gang (`/api/group/<gang>`).

    Payload : `[metadonnees_du_gang, posts]`. Fonction PURE, tolerante : un
    format inattendu rend une liste vide, jamais une exception."""
    if (
        not isinstance(payload, list)
        or len(payload) < 2
        or not isinstance(payload[1], list)
    ):
        return []
    annonces = []
    for post in payload[1]:
        if not isinstance(post, dict):
            continue
        titre = (post.get("post_title") or "").strip()
        if not titre:
            continue
        annonces.append(
            {
                "post_title": titre,
                "discovered": post.get("discovered"),
                "screen": (post.get("screen") or "").strip() or None,
            }
        )
    return annonces


def build_victim_index(
    feed_posts: Iterable,
    histories: dict[str, list[dict]],
    observer_histories: dict[str, dict[str, list[dict]]] | None = None,
) -> VictimIndex:
    """Index construit UNE fois par passe.

    `feed_posts` + `histories` = RansomLook (flux recent + historiques par gang).
    `observer_histories` = {observateur -> {gang -> annonces}} pour les autres
    observateurs (ransomware.live). Chaque annonce est un dict
    `{post_title, discovered, screen}` -- meme forme que `parse_group_history`."""
    index = VictimIndex()
    for post in feed_posts:
        index.add(
            getattr(post, "group_name", None),
            getattr(post, "post_title", None),
            getattr(post, "discovered", None),
        )
    for gang, annonces in histories.items():
        for annonce in annonces:
            index.add(
                gang,
                annonce.get("post_title"),
                annonce.get("discovered"),
                annonce.get("screen"),
            )
    for observer, par_gang in (observer_histories or {}).items():
        for gang, annonces in par_gang.items():
            for annonce in annonces:
                index.add(
                    gang,
                    annonce.get("post_title"),
                    annonce.get("discovered"),
                    annonce.get("screen"),
                    observer=observer,
                )
    return index


@dataclass(frozen=True)
class VictimCorroboration:
    status: CorroborationStatus
    claims: tuple[Claim, ...] = ()
    match: str | None = None  # "domain" | "name"

    @property
    def primary(self) -> Claim | None:
        return self.claims[0] if self.claims else None

    @property
    def groups(self) -> list[str]:
        return [c.group_name for c in self.claims]

    @property
    def first_seen_at(self) -> datetime | None:
        dates = [c.discovered_at for c in self.claims if c.discovered_at]
        return min(dates) if dates else None

    @property
    def observers(self) -> list[str]:
        """Observateurs tiers ayant vu cette victime (RansomLook,
        ransomware.live), triés — jamais un gang."""
        seen: set[str] = set()
        for claim in self.claims:
            seen |= claim.observers
        return sorted(seen)


def _claims_pour_domaine(domaine: str, index: VictimIndex) -> list[Claim]:
    normalise = _normalise_domain(domaine)
    if not normalise:
        return []
    direct = index.by_domain.get(normalise)
    if direct:
        return list(direct)
    # `mail.acme.com` -> `acme.com`, par labels, jamais par sous-chaine.
    labels = normalise.split(".")
    for debut in range(1, len(labels) - 1):
        parent = index.by_domain.get(".".join(labels[debut:]))
        if parent:
            return list(parent)
    return []


def _ordonner(claims: list[Claim], expected_group: str | None) -> tuple[Claim, ...]:
    """Le gang de NOTRE source en premier (c'est lui qui publie la page que
    nous lisons), puis par anciennete."""
    attendu = normalise_gang(expected_group)
    return tuple(
        sorted(
            claims,
            key=lambda c: (
                normalise_gang(c.group_name) != attendu,
                c.discovered_at is None,
                c.discovered_at or datetime.max.replace(tzinfo=timezone.utc),
            ),
        )
    )


def corroborate_victim(
    domains: Sequence[str],
    names: Sequence[str],
    index: VictimIndex,
    *,
    expected_group: str | None = None,
) -> VictimCorroboration:
    """Une victime (document de site de fuite) est-elle indexee par RansomLook ?

    1. Par DOMAINE, tous gangs confondus : un domaine designe une seule
       organisation, une revendication par un autre gang est une vraie double
       revendication.
    2. Par RAISON SOCIALE, **uniquement dans l'historique du gang de la
       source** : un meme nom chez un autre gang peut designer une autre
       organisation (des « Crowe », il y en a plusieurs), un nom n'a pas la
       structure d'un domaine pour borner l'ambiguite."""
    trouvees: list[Claim] = []
    for domaine in domains:
        for claim in _claims_pour_domaine(domaine, index):
            if all(
                normalise_gang(c.group_name) != normalise_gang(claim.group_name)
                for c in trouvees
            ):
                trouvees.append(claim)
    attendu = normalise_gang(expected_group)
    par_nom: list[Claim] = []
    if attendu:
        for nom in names:
            cle = name_key(nom)
            if not cle:
                continue
            par_nom = [
                c
                for c in index.by_name.get(cle, [])
                if normalise_gang(c.group_name) == attendu
            ]
            if par_nom:
                break

    if trouvees:
        # Le gang de la source, s'il publie des NOMS, est absent de l'index
        # par domaine : sa revendication, trouvee par le nom, est ajoutee.
        # Sans cela, une victime lue sur le site de NIGHT SPIRE etait
        # attribuee au seul autre gang qui la revendique (cas reel,
        # `transports-exemple.com`, 2026-09-11).
        if par_nom and all(normalise_gang(c.group_name) != attendu for c in trouvees):
            trouvees.extend(par_nom)
        return VictimCorroboration(
            CorroborationStatus.CORROBORATED,
            _ordonner(trouvees, expected_group),
            "domain",
        )
    if par_nom:
        return VictimCorroboration(
            CorroborationStatus.CORROBORATED, tuple(par_nom), "name"
        )

    return VictimCorroboration(CorroborationStatus.EXCLUSIVE)
