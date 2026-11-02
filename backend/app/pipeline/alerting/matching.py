"""Rattachement d'une detection a la ou les entites surveillees qu'elle
concerne. Logique pure (voir CONTRIBUTING.md §3.3) : prend des contrats deja
produits (DetectionContract, EntityContract), ne touche ni la DB ni Celery.

Perimetre (voir CONTRIBUTING.md §1 -- domain/email portent 83% du signal reel :
domain 61% + email 22%) : `domain`, `email_domain`, et depuis le 2026-09-04
`keyword` face aux detections `organization`, pour les victimes que les sites
de fuite nomment par leur RAISON SOCIALE sans jamais citer de domaine (cas de
SARCOMA et METAENCRYPTER, laisses inactifs faute de ce rattachement).

⚠️ Rendement mesure avant d'ecrire la brique, et faible : sur 2414 detections
`organization`, une seule raison sociale correspond a une entite surveillee
(Delta Fine Finishes) -- laquelle n'a d'ailleurs AUCUN selecteur, comme 7
autres entites actives. Le rattachement par nom ne remplace donc pas une
watchlist correctement renseignee, il la complete.

Comparaison par labels de domaine, jamais par sous-chaine (voir CONTRIBUTING.md
§8) : "operateur.sn" doit matcher "mail.operateur.sn" (vrai sous-domaine, memes
labels terminaux) mais ni "not-operateur.sn" ni "operateur.sn.evil.com" (labels
differents). Les deux cotes sont normalises avant comparaison (casse, point
final, espaces, punycode) -- voir _normalize_domain.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from app.contracts.detection import DetectionContract, DetectionType
from app.contracts.entity import EntityContract, SelectorType


def _normalize_domain(value: str) -> str:
    """Normalise un domaine pour comparaison structurelle : minuscules,
    espaces superflus retires, point final retire (RFC 1035 -- "operateur.sn."
    et "operateur.sn" designent le meme domaine), encode en punycode si le
    domaine contient de l'Unicode (IDN) pour que la comparaison par labels
    reste stable quelle que soit la forme d'origine."""
    normalized = value.strip().lower().rstrip(".")
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        # Deja en ASCII / punycode, ou forme invalide qu'on laisse telle
        # quelle : ne doit jamais lever, juste ne pas matcher plus tard.
        return normalized


def normalize_victim(value: str) -> str:
    """Identite d'une victime, pour ne pas la signaler deux fois.

    Reutilise `_normalize_domain` puis retire le `www.` de tete : les sites de
    fuite publient indifferemment `partenaire-exemple.co.za` et `www.partenaire-exemple.co.za`,
    et RansomLook la forme sans prefixe -- trois ecritures pour une seule
    organisation.

    ⚠️ Sert au DEDOUBLONNAGE d'alertes, jamais au rattachement a une entite :
    celui-ci se fait par labels (voir `_domain_matches_selector`), et rabattre
    `www.` ne suffirait pas a le remplacer.
    """
    normalized = _normalize_domain(value)
    return normalized[4:] if normalized.startswith("www.") else normalized


def victim_key(value: str | None, declared_domain: str | None = None) -> str:
    """Cle d'une victime d'alerte REGIONALE (une alerte par victime, migration
    0032) : le domaine DECLARE par l'agregateur quand la victime a ete publiee
    par sa seule raison sociale (`source_meta.victim_domain`), sinon la valeur
    detectee.

    ⚠️ SEULE definition, partagee par la generation des alertes et par la
    scission des alertes anterieures : deux definitions du meme fait finissent
    par diverger (arrive aux domaines d'infrastructure, ecrits a trois
    endroits).

    ⚠️ Une ADRESSE e-mail designe son organisation, pas une victime a part :
    la simulation du 2026-09-30 comptait `c***@quartier-exemple.co.za` et
    `quartier-exemple.co.za` pour deux victimes, soit une alerte par adresse. Le masquage
    laisse le domaine en clair (voir detect/masking.py) : c'est lui la cle."""
    valeur = declared_domain or value or ""
    if "@" in valeur:
        valeur = valeur.rsplit("@", 1)[1]
    return normalize_victim(valeur)


def _domain_matches_selector(detected_domain: str, selector_value: str) -> bool:
    """True si `detected_domain` est le domaine surveille lui-meme ou un de
    ses sous-domaines reels, par egalite des labels terminaux -- jamais par
    `in`/`contains` sur la chaine brute (voir CONTRIBUTING.md §8)."""
    detected_labels = _normalize_domain(detected_domain).split(".")
    selector_labels = _normalize_domain(selector_value).split(".")
    if len(detected_labels) < len(selector_labels):
        return False
    return detected_labels[-len(selector_labels) :] == selector_labels


def _email_domain_from_masked(value_masked: str) -> str | None:
    """Extrait le domaine d'un email masque (ex: "j***@example.com" ->
    "example.com") -- mask_email (voir pipeline/detect/masking.py) garde
    toujours le domaine en clair apres le `@`, seule la partie locale est
    masquee."""
    _, _, domain = value_masked.partition("@")
    return domain or None


# Seuls types de detection que `matching_entities` sait rattacher a une entite :
# ils sont les seuls a avoir un SelectorType equivalent (DOMAIN, EMAIL_DOMAIN).
# Tout autre type ressort systematiquement a [] plus bas.
#
# Cette liste est exportee parce que les appelants qui scannent le corpus
# (services/alert_service.py, api/routers/stats.py, api/routers/entities.py)
# doivent filtrer EN SQL et non en memoire : leur plafond de lignes est trie
# `created_at DESC`, donc charger les types non matchables les fait evincer du
# scan des detections utiles plus anciennes -- sans erreur ni log.
#
# Mesure du 2026-09-01 : 20 513 detections, dont 12 319 non matchables (61 %
# du plafond de 20 000). 193 detections matchables tombaient hors scan, dont
# 11 rattachees a une entite surveillee (distribution-exemple.co.za, institut-exemple.ma, telecom-exemple.ma, egov-exemple.sc,
# finances-exemple.go.ke...).
#
# ⚠️ Aucune alerte n'avait pour autant ete perdue : verifie en base, ces 11
# detections avaient deja ete alertees quand elles etaient plus recentes et
# donc encore dans le scan. Ne pas presenter ce correctif comme une
# recuperation d'alertes -- c'est la suppression d'un risque, pas la reparation
# d'un dommage constate.
#
# Le mecanisme a craindre n'est pas la croissance reguliere (~1 000
# detections/jour, soit 20 jours pour saturer le plafond, bien au-dela de la
# fenetre de 7 jours) mais la RAFALE : une re-detection en masse remplit le
# plafond en une passe. Le 2026-08-28, 8 120 detections ingerees dont
# 244 matchables seulement -- les 7 876 autres consommaient 39 % du plafond
# sans pouvoir produire la moindre alerte. C'est ce cas que le filtre SQL
# neutralise.
MATCHABLE_DETECTION_TYPES: tuple[str, ...] = (
    DetectionType.DOMAIN.value,
    DetectionType.EMAIL.value,
)


def matchable_detection_types(entities: list[EntityContract]) -> tuple[str, ...]:
    """Types a charger, selon ce que les entites surveillees declarent.

    ⚠️ `organization` n'est inclus QUE si au moins une entite active porte un
    selecteur `keyword`. Ce n'est pas une precaution theorique : mesure du
    2026-09-04 sur le corpus reel --
      - 2414 detections `organization`, dont **873 sont en fait des domaines**
        (le type est trompeur) ;
      - ces 873 couvrent 24 organisations surveillees... **toutes deja
        alertees** par leur detection `domain` (verifie en base : 0 valeur
        inedite) ;
      - les 1541 restantes sont de vraies raisons sociales, dont **une seule**
        correspond a une entite surveillee.
    Les inclure inconditionnellement couterait donc 2414 lignes du plafond de
    20 000 -- le mecanisme meme qui evinçait des detections utiles le
    2026-09-01 -- pour zero alerte supplementaire. Tant que personne ne declare
    de selecteur `keyword`, le cout reste nul.
    """
    types = list(MATCHABLE_DETECTION_TYPES)
    if any(
        selector.type == SelectorType.KEYWORD
        for entity in entities
        if entity.active
        for selector in entity.selectors
    ):
        types.append(DetectionType.ORGANIZATION.value)
    return tuple(types)


# Formes juridiques retirees avant comparaison : « Propane Exemple Inc. » et
# « Propane Exemple » designent la meme organisation, et les sites de fuite
# n'ecrivent pas la raison sociale de la meme facon que le registre.
_FORMES_JURIDIQUES = frozenset(
    {
        "inc",
        "llc",
        "ltd",
        "limited",
        "sa",
        "sas",
        "sarl",
        "gmbh",
        "bv",
        "nv",
        "pty",
        "corp",
        "corporation",
        "co",
        "company",
        "plc",
        "srl",
        "spa",
        "ag",
        "ab",
        "oy",
        "as",
        "llp",
        "lp",
        "pvt",
        "sl",
        "pc",
    }
)

# ⚠️ Longueur minimale d'un nom normalise. Un selecteur trop court rattacherait
# n'importe quoi : le rapprochement par nom n'a pas l'equivalent des labels de
# domaine pour se proteger structurellement, cette borne en tient lieu.
_LONGUEUR_MIN_NOM = 4


_DOMAINE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.IGNORECASE)


def _ressemble_a_un_domaine(valeur: str) -> bool:
    return bool(_DOMAINE.match(valeur.strip()))


def _normalize_org_name(value: str) -> str:
    """Forme comparable d'une raison sociale : minuscules, sans accents, sans
    ponctuation ni forme juridique.

    « Propane Exemple Inc. », « PROPANE EXEMPLE » et « Propane-Exemple, S.A. »
    rendent tous « propane exemple ».
    """
    sans_accents = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    ).lower()
    # ⚠️ Recoller les sigles pointes AVANT de decouper. Sinon « S.A. » donne
    # deux jetons `s` et `a`, qu'aucune forme juridique ne reconnait, et
    # « SOCIETE-GENERALE, S.A. » ne rejoint jamais « Societe Generale ».
    # Attrape par un test ; ne pas simplifier en retirant les jetons d'une
    # lettre, ce qui casserait « R & D Machine ».
    sans_accents = re.sub(r"\b([a-z])\.", r"\1", sans_accents)
    mots = re.sub(r"[^a-z0-9]+", " ", sans_accents).split()
    return " ".join(m for m in mots if m not in _FORMES_JURIDIQUES)


def _org_name_matches_selector(detected_name: str, selector_value: str) -> bool:
    """True si les deux raisons sociales sont la meme, apres normalisation.

    ⚠️ EGALITE, jamais inclusion -- meme doctrine que les domaines (CONTRIBUTING.md
    §8). Surveiller « Acme » ne doit pas rattacher « Acme County Sheriff »
    ni « Bank of Acme ». Un nom d'organisation n'a pas de structure en
    labels : sans l'egalite stricte, rien ne borne les faux positifs.
    """
    attendu = _normalize_org_name(selector_value)
    if len(attendu) < _LONGUEUR_MIN_NOM:
        return False
    return _normalize_org_name(detected_name) == attendu


def value_matches_watched_entity(value: str, entities: list[EntityContract]) -> bool:
    """Cette VALEUR designe-t-elle une organisation surveillee ?

    ⚠️ Independant du TYPE de detection qui la porte -- et c'est tout
    l'interet. `matching_entities` raisonne sur une detection : un domaine
    surveille porte par une detection `organization` n'y matche pas, faute de
    selecteur `keyword`. Sur les DLS, la MEME victime produit pourtant deux
    detections (`domain` et `organization`) depuis le meme document.

    Bug reel corrige le 2026-09-04 : l'alerte regionale « Afrique -- victime
    non declaree » contenait **21 organisations toutes surveillees**
    (`distribution-exemple.co.za`, `telecom-exemple.ma`, `egov-exemple.sc`, `institution-exemple.sn`...). Chacune etait
    deja alertee nominativement via sa detection `domain`, et re-signalee comme
    « non declaree » via sa detection `organization`. L'exclusion doit porter
    sur la victime, pas sur l'objet detection.
    """
    # ⚠️ Une valeur peut etre un EMAIL MASQUE (« o***@negoce-exemple.co.za ») :
    # seul son domaine est comparable. Sans cela, la passe regionale
    # re-signalait comme « non declarees » des victimes surveillees dont elle
    # avait ramasse une adresse plutot que le domaine nu -- 3 cas mesures le
    # 2026-09-04, apres un premier correctif qui ne traitait que les domaines.
    if "@" in value:
        value = _email_domain_from_masked(value) or ""
    valeur = normalize_victim(value)
    if not valeur:
        return False
    for entity in entities:
        if not entity.active:
            continue
        for selector in entity.selectors:
            if selector.type not in (SelectorType.DOMAIN, SelectorType.EMAIL_DOMAIN):
                continue
            if _domain_matches_selector(valeur, selector.value):
                return True
    return False


def matching_entities(
    detection: DetectionContract, entities: list[EntityContract]
) -> list[EntityContract]:
    """Retourne les entites actives dont au moins un selecteur correspond a
    `detection`. Ne fait aucune hypothese sur ce que l'appelant fait ensuite
    (regroupement en alerte, persistance...) -- voir pipeline/alerting/rules.py
    pour le calcul de severite, separe de ce matching."""
    detected_value: str | None
    correspond: Callable[[str, str], bool]
    if detection.type == DetectionType.DOMAIN:
        detected_value = detection.value_masked
        selector_type = SelectorType.DOMAIN
        correspond = _domain_matches_selector
    elif detection.type == DetectionType.EMAIL:
        detected_value = _email_domain_from_masked(detection.value_masked)
        selector_type = SelectorType.EMAIL_DOMAIN
        correspond = _domain_matches_selector
    elif detection.type == DetectionType.ORGANIZATION:
        # ⚠️ Beaucoup de detections `organization` portent en fait un DOMAINE
        # (873 sur 2414, mesure du 2026-09-04). Celles-la sont deja couvertes
        # par le rattachement par domaine ; les traiter ici comme des noms
        # produirait un doublon, et les traiter comme des domaines dupliquerait
        # la branche DOMAIN. On ne garde donc que ce qui ressemble a un nom.
        detected_value = detection.value_masked
        if not detected_value or _ressemble_a_un_domaine(detected_value):
            return []
        selector_type = SelectorType.KEYWORD
        correspond = _org_name_matches_selector
    else:
        return []

    if not detected_value:
        return []

    matches = []
    for entity in entities:
        if not entity.active:
            continue
        for selector in entity.selectors:
            if selector.type != selector_type:
                continue
            if correspond(detected_value, selector.value):
                matches.append(entity)
                break
    return matches


def most_specific(matched: list[EntityContract]) -> list[EntityContract]:
    """Retire les groupes dont une FILIALE correspond aussi (décision D2 du
    2026-10-05) : c'est la filiale touchée qui doit agir, le groupe voit
    l'alerte par regroupement. Sans cette règle, un domaine déclaré par le
    groupe ET la filiale produirait deux alertes pour un seul incident.

    Un groupe qui correspond SEUL (aucune de ses filiales) est conservé."""
    parents_d_une_correspondance = {e.parent_id for e in matched if e.parent_id}
    return [e for e in matched if e.id not in parents_d_une_correspondance]
