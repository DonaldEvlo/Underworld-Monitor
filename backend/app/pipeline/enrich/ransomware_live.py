"""ransomware.live -- SECOND observateur de corroboration (2026-09-15).

Meme role que RansomLook (voir ransomlook_corroboration.py) : un agregateur
clearnet qui indexe les victimes revendiquees sur les DLS de gangs. Il n'est
PAS independant de RansomLook (les deux lisent le meme site du gang), mais son
UNION augmente la COUVERTURE -- mesure du 2026-09-14 :
  - il suit 396 groupes, dont APT73, CMD, PEAR que RansomLook ignore
    totalement (0 % de corroboration chez nous jusqu'ici) ;
  - sur APT73 : 157 victimes indexees, 94 % de NOS victimes APT73 retrouvees.

⚠️ Schema plus riche que RansomLook : champ `domain` STRUCTURE (pas un titre a
parser), plus `country`, `activity` (secteur), `attackdate`, `screenshot`
(URL absolue). Ces metadonnees sont exposees pour un usage futur (geo,
secteur) mais ne servent pas au rapprochement lui-meme.

⚠️ Le `claim_url` renvoye est un `.onion` du gang -- NON citable en clearnet,
comme le `link` de RansomLook. On ne cite que `screenshot` (clearnet).

Fonctions PURES : le reseau est fait par l'appelant (corroboration_service),
ce qui les rend testables sans appel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.pipeline.enrich.ransomlook_corroboration import (
    OBSERVER_RANSOMWARE_LIVE,  # noqa: F401 -- reexporte pour l'appelant
    _domain_candidates,
    name_key,
    normalise_gang,
)
from app.pipeline.enrich.ttp import extract_cves

_API_BASE = "https://api.ransomware.live"


def group_victims_url(gang: str) -> str:
    """Endpoint des victimes d'un gang. ⚠️ `/v2/groupvictims/<gang>` -- PAS
    `/v2/group/<gang>` (qui ne renvoie que des metadonnees de groupe, verifie
    le 2026-09-14)."""
    return f"{_API_BASE}/v2/groupvictims/{_slug(gang)}"


def _slug(gang: str) -> str:
    """Identifiant du gang dans l'URL : « the gentlemen » -> `thegentlemen`.

    ⚠️ Bug constate le 2026-09-29 : le nom etait insere tel quel, ESPACE
    compris. `/v2/groupvictims/the gentlemen` ne rend rien, alors que
    `/v2/groupvictims/thegentlemen` rend 888 victimes -- dont Hollard et
    Exemple Risk. Tous les gangs a nom compose (`the gentlemen`, `inc ransom`)
    etaient donc muets en silence, et la cle de cache, elle deja normalisee,
    masquait l'ecart."""
    return normalise_gang(gang) or gang.strip().lower()


RECENT_VICTIMS_URL = f"{_API_BASE}/v2/recentvictims"


def parse_group_victims(payload) -> list[dict]:
    """Victimes d'un gang -> annonces `{post_title, discovered, screen}`,
    forme consommee par `build_victim_index`.

    Pour chaque victime on emet jusqu'a DEUX annonces : une par le `domain`
    (rapprochement par domaine) et, si `victim` est une raison sociale
    distincte, une par ce nom (rapprochement par nom, borne au gang de la
    source). `screen` = URL de capture ABSOLUE (`https://images.ransomware.live/...`).

    Tolerant : un format inattendu rend une liste vide, jamais une exception."""
    if not isinstance(payload, list):
        return []
    annonces: list[dict] = []
    for victim in payload:
        if not isinstance(victim, dict):
            continue
        discovered = victim.get("discovered") or victim.get("attackdate")
        screen = (victim.get("screenshot") or "").strip() or None
        domaine = (victim.get("domain") or "").strip()
        nom = (victim.get("victim") or "").strip()
        emises: set[str] = set()
        for candidat in (domaine, nom):
            if not candidat or candidat in emises:
                continue
            emises.add(candidat)
            annonces.append(
                {"post_title": candidat, "discovered": discovered, "screen": screen}
            )
    return annonces


def group_profile_url(gang: str) -> str:
    """Endpoint du PROFIL d'un gang (`ttps`, `tools`, `description`).

    ⚠️ C'est bien `/v2/group/<gang>` -- l'endpoint juge « inutile » le
    2026-09-14 parce qu'il ne renvoie aucune victime. Il n'etait pas inutile,
    il repondait a une AUTRE question : non pas « qui a-t-il frappe » mais
    « comment travaille-t-il ». Mesure du 2026-09-15 : 61 des 396 groupes y
    portent des TTP MITRE structures.

    ⚠️ RATE LIMIT MESURE : ~1 requete par minute sur cette API. Un appel par
    gang et par jour maximum, avec cache -- comme les historiques de
    corroboration."""
    return f"{_API_BASE}/v2/group/{_slug(gang)}"


def profile_payload(payload) -> list[dict] | None:
    """Reponse brute de `/v2/group/<gang>` -> `[profil]`, ou None.

    ⚠️ L'API sert sa limite de debit en HTTP 200 avec un OBJET
    (`{"message": "1 per 1 minute"}`), de meme forme qu'un profil. Le
    confondre avec un profil le mettrait en cache comme un gang « sans
    mode operatoire documente » pendant des jours. None = indisponible,
    jamais mis en cache."""
    if not isinstance(payload, dict) or not payload:
        return None
    if set(payload) <= {"message", "error", "detail", "status"}:
        return None
    return [payload]


@dataclass(frozen=True)
class GangTechnique:
    """Une technique MITRE ATT&CK attribuee a un GANG.

    ⚠️ DECLAREE PAR UN TIERS, ET SUR LE GANG -- PAS SUR L'INCIDENT. C'est le
    mode operatoire habituel du groupe, observe par des chercheurs sur
    d'autres victimes. Cela ne dit PAS comment CETTE organisation a ete
    compromise. Confondre les deux ferait ecrire a un rapport « vous avez ete
    compromis via CVE-2024-55591 » alors que rien ne l'etablit -- exactement
    la faute du modele qui avait ecrit « l'organisation Krybit a confirme »."""

    tactic_id: str
    tactic_name: str
    technique_id: str
    technique_name: str
    details: str | None


@dataclass(frozen=True)
class GangProfile:
    gang: str
    techniques: tuple[GangTechnique, ...]
    # Tous les outils, a plat (compatibilite) ...
    tools: tuple[str, ...]
    cves: tuple[str, ...]
    # ... et regroupes par CATEGORIE, telle que publiee par la source
    # (`CredentialTheft`, `Exfiltration`, `RMM-Tools`...). « "" » = sans
    # categorie. C'est la categorie qui rend l'outil exploitable par une
    # victime : RClone sous « Exfiltration » dit quoi chercher dans ses flux.
    tool_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.techniques or self.tools or self.cves)


def _groupes_d_outils(brut) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Outils d'un profil, par categorie, quelle que soit la forme publiee.

    ⚠️ Mesure du 2026-09-30 : `tools` est une LISTE contenant UN DICTIONNAIRE
    categorie -> noms (`[{"CredentialTheft": ["Mimikatz", ...], ...}]`). La
    premiere version n'acceptait que des chaines : elle jetait tout, en
    silence, et declarait LockBit « sans mode operatoire documente » alors que
    la source listait 51 outils. On accepte donc liste de chaines, liste de
    dictionnaires et dictionnaire. Les noms « defangues » (`File[.]io`) sont
    gardes tels quels : c'est la bonne pratique pour partager un indicateur."""
    groupes: dict[str, list[str]] = {}

    def ajouter(categorie: str, nom) -> None:
        if not isinstance(nom, (str, int)):
            return
        nom = str(nom).strip()
        noms = groupes.setdefault(categorie, [])
        if nom and nom not in noms:
            noms.append(nom)

    elements = (
        brut if isinstance(brut, list) else [brut] if isinstance(brut, dict) else []
    )
    for element in elements:
        if isinstance(element, dict):
            for categorie, noms in element.items():
                for nom in noms if isinstance(noms, list) else [noms]:
                    ajouter(str(categorie).strip(), nom)
        else:
            ajouter("", element)
    return tuple((c, tuple(n)) for c, n in groupes.items() if n)


def parse_group_profile(gang: str, payload) -> GangProfile:
    """Profil TTP d'un gang -> techniques MITRE + outils + CVE citees.

    Les CVE ne vivent PAS dans un champ dedie : elles sont noyees dans le
    `technique_details` en texte libre (« Exploitation of CVE-2024-55591 —
    FortiOS/FortiProxy authentication bypass »). Mesure du 2026-09-15 : c'est
    le seul endroit du payload qui en contient. On les extrait avec
    `ttp.extract_cves`, deja teste.

    Tolerant : un format inattendu rend un profil VIDE, jamais une exception.
    Un profil vide se lit « non documente », jamais « pas de methode »."""
    if not isinstance(payload, dict):
        return GangProfile(gang=gang, techniques=(), tools=(), cves=())

    techniques: list[GangTechnique] = []
    for tactique in payload.get("ttps") or []:
        if not isinstance(tactique, dict):
            continue
        tid = str(tactique.get("tactic_id") or "").strip()
        tname = str(tactique.get("tactic_name") or "").strip()
        for tech in tactique.get("techniques") or []:
            if not isinstance(tech, dict):
                continue
            tech_id = str(tech.get("technique_id") or "").strip()
            if not tech_id:
                continue
            details = str(tech.get("technique_details") or "").strip() or None
            techniques.append(
                GangTechnique(
                    tactic_id=tid,
                    tactic_name=tname,
                    technique_id=tech_id,
                    technique_name=str(tech.get("technique_name") or "").strip(),
                    details=details,
                )
            )

    groupes = _groupes_d_outils(payload.get("tools"))
    tools = tuple(dict.fromkeys(nom for _, noms in groupes for nom in noms))
    cves = tuple(
        extract_cves(" ".join(t.details for t in techniques if t.details) or None)
    )
    return GangProfile(
        gang=gang,
        techniques=tuple(techniques),
        tools=tools,
        cves=cves,
        tool_groups=groupes,
    )


@dataclass(frozen=True)
class VictimIntel:
    """Ce qu'un tiers sait d'UNE victime, au-dela du simple « elle est
    revendiquee ». Alimente la criticite.

    ⚠️ AUCUNE PII, ET C'EST VERIFIE, PAS SUPPOSE. Inspection du payload reel
    (2026-09-15) : `employees`/`users`/`thirdparties` sont des ENTIERS,
    `employees_url`/`users_url` des NOMBRES d'URL (pas des URL), et
    `last_*_compromised` des DATES ISO. Aucun identifiant, aucune adresse,
    aucun mot de passe ne transite. On enregistre COMBIEN et DEPUIS QUAND,
    jamais QUI ni QUOI -- meme forme que le booleen `known_breached` de HIBP.

    ⚠️ `stealer_families` nomme la famille de logiciel voleur (RedLine, Lumma,
    Raccoon...), pas une victime ni un operateur. C'est de la methode, au
    niveau de l'organisation."""

    attack_date: str | None
    country: str | None
    activity: str | None  # secteur declare (« Healthcare », « Manufacturing »)
    data_size: str | None
    # Comptes d'exposition aux logs de voleurs d'identifiants.
    # ⚠️ `None` = NON FOURNI par la source, `0` = fourni et nul. ransomware.live
    # a retire le champ `infostealer` vers le 2026-09-23 : le ramener a 0
    # affichait « 0 identifiant expose » sur 49 alertes sur 56, une mesure
    # que personne n'avait faite.
    compromised_employees: int | None
    compromised_users: int | None
    compromised_thirdparties: int | None
    stealer_families: tuple[str, ...]
    last_employee_compromised: str | None
    last_user_compromised: str | None

    @property
    def has_credential_exposure(self) -> bool:
        """Des identifiants de cette organisation apparaissent dans des logs de
        voleurs. ⚠️ Se lit « exposition connue », jamais « compte utilisable » :
        le projet ne teste JAMAIS un identifiant (regle 1)."""
        return bool((self.compromised_employees or 0) or (self.compromised_users or 0))

    @property
    def privileged_exposure(self) -> bool:
        """L'exposition touche des EMPLOYES (interne), pas seulement des
        clients. C'est la distinction demandee entre « citoyen simple » et
        personnel de l'organisation -- posee sur le ROLE vis-a-vis de
        l'organisation, jamais sur la personne."""
        return (self.compromised_employees or 0) > 0


# Valeurs de `infostealer_stats` qui ne nomment aucune famille reelle.
_FAMILLES_NON_INFORMATIVES = {"unknown", "generic stealer", ""}

# Valeurs sentinelles de `activity` qui ne nomment aucun secteur.
_SECTEURS_NON_INFORMATIFS = {"not found", "unknown", "n/a", "other", ""}

# ⚠️ SEUIL DE DATE D'IMPORT EN LOT. Au-dela de cette part des victimes d'un
# gang partageant la MEME date, cette date ne date plus une attaque : elle
# date une indexation de masse chez l'agregateur.
#
# Mesure du 2026-09-15, gang par gang -- part de la date la plus frequente :
#   apt73 44 % | payload 15 % | krybit 10 % | direwolf 10 %
#   nightspire 3 % | beast 3 % | lockbit3 2 %
# APT73 se detache nettement : 57 de ses 129 victimes portent 2026-04-27, y
# compris egov-exemple.sc, finances-exemple.go.ke, media-exemple.ma et telecom-exemple.ma -- des incidents qui ne se
# sont evidemment pas produits le meme jour. Les autres gangs publient bien
# par lots, mais de facon diffuse.
#
# 25 % separe les deux regimes sans couper au plus juste. Meme famille de
# piege que le `data-timer` de LockBit et la date d'inscription de l'auteur
# sur Dread : un champ present partout, plausible, et qui ne mesure pas ce
# qu'on croit. ⚠️ Ne pas relever ce seuil sans refaire la mesure.
_PART_MAX_DATE_PARTAGEE = 0.25


def _compte(valeur) -> int | None:
    """Compteur FOURNI par la source, ou `None` s'il ne l'est pas.

    ⚠️ Champ absent, texte ou negatif -> `None`, jamais 0 : une valeur
    illisible n'est pas une mesure nulle (meme doctrine que
    `corroboration_status` NULL).
    """
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        n = int(valeur)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _date_reelle(valeur) -> str | None:
    """⚠️ `1970-01-01T00:00:00+00:00` est l'epoch Unix employe comme « jamais »
    -- mesure sur le payload reel. L'afficher comme une date de compromission
    ferait remonter 1970 dans l'interface."""
    texte = str(valeur or "").strip()
    if not texte or texte.startswith("1970-01-01"):
        return None
    return texte


def batch_indexing_dates(payload) -> frozenset[str]:
    """Dates (`YYYY-MM-DD`) partagees par une part anormale des victimes d'un
    gang -- ce sont des dates d'INDEXATION en lot, pas des dates d'attaque.

    A calculer sur le payload COMPLET du gang : une date ne devient suspecte
    que rapportee a l'ensemble de ses victimes. Sur une victime isolee, elle
    est indiscernable d'une vraie date."""
    if not isinstance(payload, list) or not payload:
        return frozenset()
    comptes: dict[str, int] = {}
    total = 0
    for victim in payload:
        if not isinstance(victim, dict):
            continue
        jour = _date_reelle(victim.get("attackdate"))
        if not jour:
            continue
        total += 1
        jour = jour[:10]
        comptes[jour] = comptes.get(jour, 0) + 1
    if total < 20:  # trop peu de victimes pour qu'une part soit significative
        return frozenset()
    return frozenset(
        jour for jour, n in comptes.items() if n / total > _PART_MAX_DATE_PARTAGEE
    )


def parse_victim_intel(payload) -> dict[str, VictimIntel]:
    """Renseignements par domaine normalise, pour les victimes d'un gang.

    Couverture MESUREE sur lockbit3 (2016 victimes) : `attackdate` 100 %,
    `activity` 100 %, `country` 62 %, identifiants exposes 37 % (employes
    20 %, tiers 32 %). Familles citees : RedLine 193, Lumma 173, Raccoon 163,
    StealC 132, Vidar 122, Azorult 121.

    Tolerant : un format inattendu rend un dictionnaire vide."""
    intel: dict[str, VictimIntel] = {}
    for victim, enregistrement in _victim_intel_records(payload):
        for candidat in _domain_candidates(victim.get("domain") or ""):
            intel.setdefault(candidat, enregistrement)
    return intel


# Qualificatif FINAL d'un nom publie : « XYZ Investments(Egypt) »,
# « LAMEXA, Egypt ». NIGHT SPIRE ajoute le pays au nom de la victime, alors
# que ransomware.live le range dans `country` (« XYZ Investments »).
_QUALIFICATIF_FINAL = re.compile(r"\s*(?:\([^()]*\)|,[^,()]*)\s*$")


def victim_name_keys(value: str | None) -> list[str]:
    """Cles de rapprochement d'une raison sociale : le nom complet, puis le nom
    sans son qualificatif final (parenthese ou virgule).

    ⚠️ EGALITE apres normalisation, jamais inclusion (`name_key`) ; le nom
    complet passe toujours en premier, le nom raccourci n'est qu'un repli."""
    cles: list[str] = []
    if not value:
        return cles
    for variante in (value, _QUALIFICATIF_FINAL.sub("", value)):
        cle = name_key(variante)
        if cle and cle not in cles:
            cles.append(cle)
    return cles


def parse_victim_intel_by_name(payload) -> dict[str, list[VictimIntel]]:
    """Renseignements indexes par NOM de victime, pour les victimes publiees
    par leur seule raison sociale (sans domaine).

    Une liste par cle : deux victimes du meme gang au meme nom normalise sont
    AMBIGUES, et l'appelant ne doit alors rien conclure -- un secteur attribue
    a la mauvaise organisation fausserait sa gravite."""
    intel: dict[str, list[VictimIntel]] = {}
    for victim, enregistrement in _victim_intel_records(payload):
        for cle in victim_name_keys(victim.get("victim")):
            intel.setdefault(cle, []).append(enregistrement)
    return intel


def _victim_intel_records(payload) -> list[tuple[dict, VictimIntel]]:
    """(victime brute, renseignements) pour chaque victime d'un gang.

    Tolerant : un format inattendu rend une liste vide."""
    if not isinstance(payload, list):
        return []
    lots = batch_indexing_dates(payload)
    enregistrements: list[tuple[dict, VictimIntel]] = []
    for victim in payload:
        if not isinstance(victim, dict):
            continue
        infos = victim.get("infostealer")
        if not isinstance(infos, dict):
            infos = {}
        familles = tuple(
            sorted(
                f
                for f in (infos.get("infostealer_stats") or {})
                if isinstance(f, str)
                and f.strip().lower() not in _FAMILLES_NON_INFORMATIVES
            )
        )
        jour = _date_reelle(victim.get("attackdate"))
        # ⚠️ Une date d'import en lot est ECARTEE, pas conservee « faute de
        # mieux » : une date fausse est pire qu'une date absente -- elle se
        # propagerait dans le tri par fraicheur et dans le rapport PDF.
        if jour and jour[:10] in lots:
            jour = None
        secteur = (victim.get("activity") or "").strip()
        enregistrements.append(
            (
                victim,
                VictimIntel(
                    attack_date=jour,
                    country=(victim.get("country") or "").strip() or None,
                    activity=(
                        None
                        if secteur.lower() in _SECTEURS_NON_INFORMATIFS
                        else secteur
                    ),
                    data_size=(victim.get("data_size") or "").strip() or None,
                    compromised_employees=_compte(infos.get("employees")),
                    compromised_users=_compte(infos.get("users")),
                    compromised_thirdparties=_compte(infos.get("thirdparties")),
                    stealer_families=familles,
                    last_employee_compromised=_date_reelle(
                        infos.get("last_employee_compromised")
                    ),
                    last_user_compromised=_date_reelle(
                        infos.get("last_user_compromised")
                    ),
                ),
            )
        )
    return enregistrements


@dataclass(frozen=True)
class PressCoverage:
    """Confirmation EXTERNE d'un incident : un article de presse ou une
    declaration officielle, indexe par ransomware.live pour cette victime.

    C'est le seul signal du projet qui ne vienne ni du gang, ni d'un
    agregateur lisant le meme site que nous : il repond a « la fuite est-elle
    reelle ? », la ou la corroboration repond a « notre lecture est-elle
    juste ? ».

    ⚠️ CONTRAT SEPARE DE `VictimIntel`, volontairement : celui-ci est la
    frontiere de la regle 2 (compteurs, dates, libelles uniquement), verrouillee
    par `TestAucunePII`. Des URL n'y ont pas leur place.

    ⚠️ Le `summary` du payload N'EST PAS repris : c'est un resume redige par
    un tiers, qui peut nommer des personnes. L'article lui-meme reste
    consultable par son lien -- minimisation."""

    source_url: str | None  # l'article ou le communique d'origine
    evidence_url: str | None  # la fiche ransomware.live qui l'indexe


def _url_publique(valeur) -> str | None:
    """URL clearnet citable, sinon None.

    ⚠️ Filtre de SECURITE autant que de pertinence : ces valeurs viennent d'un
    tiers et finissent dans un `href`. Seuls `http`/`https` passent -- un
    `javascript:` serait execute au clic. Les `.onion` sont ecartes : ils
    exigent Tor et ne sont pas une preuve citable."""
    texte = str(valeur or "").strip()
    if not texte.lower().startswith(("https://", "http://")):
        return None
    hote = texte.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].lower()
    if not hote or hote.endswith(".onion") or any(c.isspace() for c in texte):
        return None
    return texte


def parse_press_coverage(payload) -> dict[str, PressCoverage]:
    """Couverture presse par domaine normalise, pour les victimes d'un gang.

    Couverture MESUREE le 2026-09-24 sur les 14 gangs suivis : 409 victimes
    sur 8 184 (5 %). Forme observee sur 393 cas : toujours un objet
    `{link, source, summary}`, `source` vide dans 5 cas -- la fiche
    ransomware.live reste alors la seule preuve.

    ⚠️ Une ABSENCE de couverture ne signifie pas « fuite fausse » : la presse
    couvre surtout les grandes organisations, et avec retard. Seule la
    presence porte une information.

    Tolerant : un format inattendu rend un dictionnaire vide."""
    if not isinstance(payload, list):
        return {}
    couverture: dict[str, PressCoverage] = {}
    for victim in payload:
        if not isinstance(victim, dict):
            continue
        presse = victim.get("press")
        if not isinstance(presse, dict):
            continue
        enregistrement = PressCoverage(
            source_url=_url_publique(presse.get("source")),
            evidence_url=_url_publique(presse.get("link")),
        )
        if not (enregistrement.source_url or enregistrement.evidence_url):
            continue
        for candidat in _domain_candidates(victim.get("domain") or ""):
            couverture.setdefault(candidat, enregistrement)
    return couverture


def victim_metadata(payload) -> dict[str, dict]:
    """Metadonnees par domaine normalise : `{country, activity, data_size}`.

    Exposees pour un usage FUTUR (enrichir la geo, le secteur) -- non
    persistees aujourd'hui. Ne sert pas au rapprochement."""
    if not isinstance(payload, list):
        return {}
    meta: dict[str, dict] = {}
    for victim in payload:
        if not isinstance(victim, dict):
            continue
        for candidat in _domain_candidates(victim.get("domain") or ""):
            meta.setdefault(
                candidat,
                {
                    "country": (victim.get("country") or "").strip() or None,
                    "activity": (victim.get("activity") or "").strip() or None,
                    "data_size": (victim.get("data_size") or "").strip() or None,
                },
            )
    return meta
