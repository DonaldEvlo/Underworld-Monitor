"""Regles de criticite et de generation d'alerte. Logique pure (voir
CONTRIBUTING.md §3.3) : ne touche ni la DB ni Celery, prend des DetectionContract
deja produits par pipeline/detect/registry.py et retourne des decisions.

Echelle de gravite (question : quel impact si la fuite est reelle ?) :

    CRITICAL  incident de moins de 30 jours ET secteur critique
    HIGH      secteur critique, quel que soit l'age de l'incident
    MEDIUM    victime rattachee a une organisation surveillee, sans aggravant
    LOW       ni rattachee, ni pertinente, ni corroboree (jamais remontee)

Secteurs critiques : les secteurs « hautement critiques » de la directive NIS2
(annexe I) exprimes dans le vocabulaire `activity` de ransomware.live --
administration, sante, finance, energie et eau, transports. Un secteur ou une
date inconnus n'elevent rien.

La credibilite (la fuite est-elle reelle ?) est un axe DISTINCT, calcule dans
credibility.py : une confirmation par la presse ou par un agregateur rend une
fuite plus sure, pas plus grave. Le volume annonce est affiche, il n'eleve
pas la gravite. Modifier cette echelle est une decision structurante a
signaler avant de coder (CONTRIBUTING.md §9.3)."""

from __future__ import annotations

from app.contracts.alert import AlertSeverity
from app.contracts.detection import DetectionContract, DetectionType

# Types a fort impact immediat (acces financier ou identifiants) qui elevent
# une detection deja validee+pertinente de HIGH a CRITICAL.
_CRITICAL_TYPES = {DetectionType.CARD, DetectionType.IBAN, DetectionType.CREDENTIALS}

# Seuil minimum de severite qui declenche une alerte : LOW (is_relevant=false) ne remonte jamais
# a un analyste, sinon les 5503 detections du corpus noieraient le signal
# (CONTRIBUTING.md §8).
ALERT_THRESHOLD = AlertSeverity.MEDIUM

# Secteurs a IMPACT eleve, repris des secteurs « hautement critiques » de la
# directive NIS2 (annexe I) et exprimes dans le vocabulaire `activity` de
# ransomware.live -- releve EXHAUSTIF le 2026-09-26 sur 3 637 victimes
# (LockBit + Akira) : 14 valeurs seulement. Correspondance :
#   administration publique      -> Government & Defense
#   sante                        -> Healthcare
#   banque, infrastructures fin. -> Financial Services
#   energie, eau potable/usee    -> Energy & Utilities
#   transports                   -> Transportation
# ⚠️ « Technology » n'y est PAS, bien que NIS2 cite les services TIC : la
# valeur couvre aussi bien un hebergeur critique qu'un editeur de logiciel
# grand public -- trop large pour porter une gravite. Idem « Education ».
# Poids mesure : 23 % des victimes mondiales de ces deux gangs, 16 de nos
# 34 alertes (la liste de surveillance compte beaucoup d'institutions).
CRITICAL_SECTORS: frozenset[str] = frozenset(
    {
        "Government & Defense",
        "Healthcare",
        "Financial Services",
        "Energy & Utilities",
        "Transportation",
    }
)


def is_critical_sector(sector: str | None) -> bool:
    """Secteur a impact eleve. Un secteur INCONNU n'eleve rien : une donnee
    absente ne doit pas faire monter la gravite (meme doctrine que la date
    d'incident inconnue, qui n'est pas « fraiche »)."""
    return (sector or "").strip() in CRITICAL_SECTORS


_SEVERITY_ORDER = [
    AlertSeverity.LOW,
    AlertSeverity.MEDIUM,
    AlertSeverity.HIGH,
    AlertSeverity.CRITICAL,
]


def severity_for_detection(
    detection: DetectionContract,
    *,
    matches_watched_entity: bool = False,
    corroborated: bool = False,
    victim_published_by_attacker: bool = False,
    announced_volume: bool = False,
    incident_is_fresh: bool = False,
    privileged_credential_exposure: bool = False,
    critical_sector: bool = False,
) -> AlertSeverity:
    """Applique l'echelle de gravite (en-tete du module) a une detection unique.

    `matches_watched_entity` : la detection est rattachee a une entite
    surveillee (voir matching.py). Dans ce cas elle ne peut pas retomber en
    LOW, meme si `is_relevant` est faux.

    Pourquoi : `is_relevant` est calcule a l'ingestion en confrontant le
    *document* a la watchlist generique (voir detect/keyword_match.py), qui
    contient du vocabulaire de menace ("breach", "data leak"...). Un document
    factuel et court ne contient aucun de ces mots et sort donc en
    is_relevant=false -- constate en usage reel sur les annonces d'agregateur
    de leak sites, de la forme "Groupe: X / Victime annoncee: Y / Decouvert
    le: Z" : une victime de ransomware explicitement revendiquee, le signal le
    plus fiable du corpus, etait classee LOW et n'alertait jamais.

    Le rattachement a une entite surveillee EST la pertinence, et une
    pertinence plus forte que la watchlist : l'analyste a explicitement declare
    surveiller cette organisation. `is_relevant` reste un signal secondaire,
    qui continue de faire monter la severite quand il est present.

    `victim_published_by_attacker` : la detection vient d'une source qui
    publie ses victimes (site de fuite de gang -- voir
    detect/announcement_filter.source_publishes_victims, seule autorite sur
    cette liste). Ajoute le 2026-09-04 : sans lui l'echelle etait une
    constante.

    `announced_volume` : le document annonce un volume exfiltre non nul (une
    detection `volume` y est rattachee). Ce n'est pas la taille qui compte --
    elle est de toute facon affichee a l'analyste -- mais le fait que le gang
    ait chiffre sa revendication.

    `corroborated` : un observateur INDEPENDANT confirme cette victime (voir
    enrich/ransomlook_corroboration.py, statut `corroborated`). Ajoute le
    2026-09-01 sur decision de perimetre, apres mesure.

    Pourquoi ce drapeau plutot que `validated` : mesure du 2026-09-01 -- la
    branche HIGH etait INATTEIGNABLE. Elle exige `validated=true` sur une
    detection rattachee, or **les 1216 detections `domain` validees sont
    toutes des `.onion`** et **aucun email n'est jamais valide** ; un `.onion`
    ne matche jamais un selecteur clearnet surveille. Resultat : 0 des 692
    rattachements valide, et les 120 alertes toutes `medium`. La taxonomie
    a 4 niveaux ne produisait qu'une seule valeur.

    `validated` ne pouvait pas porter cette echelle : pour un domaine il ne
    signifie que « format .onion reconnu », pas « fait confirme ». La
    corroboration, elle, repond a la bonne question -- « quelqu'un d'autre
    voit-il cette victime ? » -- et existe deja en base (migrations 0012/0013),
    avec attribution du gang. Aucune collecte nouvelle n'est requise.

    ⚠️ `exclusive` n'est PAS un doute (voir CONTRIBUTING.md) : nous lisons le site de
    fuite a la source, l'agregateur ne l'a peut-etre pas encore indexe. Seul
    `corroborated` eleve la severite ; `exclusive` et `unknown` la laissent
    inchangee, ils ne l'abaissent jamais.

    ⚠️ La corroboration LEVE aussi le plancher LOW, y compris sans rattachement
    ni `is_relevant` -- decision du 2026-09-01. Motif : `is_relevant` est
    calcule en confrontant le document a une watchlist de vocabulaire de menace,
    si bien qu'une annonce purement factuelle (« Groupe X / Victime Y ») en
    sort a false alors que c'est le signal le plus fiable du corpus. Mesure :
    28 des 65 victimes corroborees etaient dans ce cas et retombaient en LOW,
    donc invisibles. Un tiers qui NOMME la victime avec attribution de gang
    vaut mieux qu'un mot-cle absent.

    C'est ce qui permet a une institution HORS perimetre de surveillance de
    porter tout de meme une severite (voir services/detection_severity_service
    et migration 0015) : elle ne declenche pas d'alerte -- l'alerte reste
    reservee aux entites surveillees -- mais elle cesse d'etre invisible.

    ⚠️ CRITICAL est desormais ATTEIGNABLE par la voie « revendiquee ET
    corroboree ». L'autre voie, ci-dessous, reste fermee.

    ⚠️ La branche CRITICAL par TYPE reste volontairement inatteignable. Elle exige un
    type `card`/`iban`/`credentials` rattache a une entite, or `matching.py`
    ne gere que DOMAIN/EMAIL. Les 153 detections `card` qui seraient eligibles
    (validees ET pertinentes) viennent de forums de carding ; les rattacher a
    une organisation supposerait de passer par le porteur de la carte, donc de
    traiter de la PII d'individus -- contraire aux regles 1 et 2. Decision du
    2026-09-01 : hors perimetre, assume et documente, pas un oubli."""
    if not detection.is_relevant and not matches_watched_entity and not corroborated:
        return AlertSeverity.LOW

    # ⚠️ VICTIME NOMMEE PAR L'ATTAQUANT — le critere qui rend l'echelle
    # utilisable. Mesure du 2026-09-04 sur les 243 detections deja alertees :
    # 40 % viennent d'un site de fuite (`dls`), 59 % d'un forum. Or les deux ne
    # disent pas la meme chose. Sur un site de fuite, le gang PUBLIE lui-meme
    # l'organisation comme sa victime : le document EST la revendication, et
    # l'audit du 2026-08-26 mesure 0 % de bruit d'infrastructure sur ces
    # sources contre 34 a 96 % sur les forums. Une mention sur un forum est un
    # signalement ; une publication sur un DLS est une revendication.
    #
    # Sans ce critere l'echelle etait une CONSTANTE : les 32 alertes reelles
    # etaient toutes `medium`, les 4 niveaux de l'echelle ne produisant
    # qu'une valeur.
    # ⚠️ ATTENTION AU REMPLACEMENT D'UNE CONSTANTE PAR UNE AUTRE. Une premiere
    # version faisait passer TOUTE victime revendiquee en HIGH : mesure sur les
    # 32 alertes reelles -- 30 HIGH, 1 CRITICAL, 1 MEDIUM. Soit 94 % de HIGH,
    # exactement aussi peu utile que 100 % de MEDIUM. Etre publie sur un site
    # de fuite est le cas NORMAL de nos alertes, pas l'exception : c'est de la
    # que vient le signal (audit du 2026-08-26).
    #
    # Il faut donc un second critere qui partage cette population. Mesure des
    # candidats sur les 31 alertes issues d'un site de fuite :
    #   - volume annonce      : 22 documents sur 51  -> partage bien
    #   - fraicheur (7 jours) :  1 alerte sur 31     -> ne partage rien
    #   - corroboration       :  1 alerte sur 31     -> deja utilise
    # Le volume l'emporte, et il a un sens : un gang qui revendique la victime
    # ET annonce 490 Go exfiltres formule une revendication plus lourde que
    # celui qui se contente de nommer l'organisation.
    #
    # Repartition obtenue sur les alertes reelles : 1 CRITICAL, 7 HIGH,
    # 24 MEDIUM -- une echelle qui hierarchise, enfin.
    # ⚠️ REFONTE DU 2026-09-15 (arbitrage de projet, §9.3) -- LA
    # CORROBORATION N'ELEVE PLUS RIEN PAR ELLE-MEME.
    #
    # Elle devient une marque de VERIFIABILITE (« un tiers publie la meme
    # annonce, notre lecture est juste »), pas un facteur de risque -- SAUF
    # sur un incident FRAIS, ou le fait qu'un agregateur l'ait deja indexe
    # signifie que la revendication s'est propagee vite.
    #
    # ⚠️ Et c'est a DOUBLE TRANCHANT, d'ou le refus d'en faire un simple
    # multiplicateur : sur un incident frais, « vue par nous seuls » a aussi
    # de la valeur -- nous sommes en avance et l'organisation a encore le
    # temps d'agir. Aucun des deux n'est « pire » dans l'absolu.
    #
    # POURQUOI CE CHANGEMENT -- mesure du 2026-09-15. Avec l'ancienne regle,
    # 31 des 33 alertes reelles etaient corroborees et `refresh_alert_severities`
    # aurait bascule **30 sur 33 en CRITICAL** : la troisieme constante en
    # trois tentatives (100 % MEDIUM, puis 94 % HIGH). Cause mesuree : l'age.
    # Age reel des 32 victimes alertees -- mediane **140 jours**, etendue
    # 39 j -> 956 j (les victimes LockBit sont des incidents de 2023), et
    # **0 incident sous 30 jours**. Ce corpus est un rattrapage historique :
    # sa corroboration est de la verifiabilite, pas de l'urgence.
    #
    # ⚠️ `announced_volume` cesse aussi d'elever seul. Il avait ete retenu le
    # 2026-09-04 faute de mieux ; l'exposition d'identifiants dit la meme
    # chose en mieux -- non pas « le gang se vante d'un gros butin » mais
    # « un chemin d'intrusion existe ». Le parametre est conserve : il reste
    # affiche a l'analyste et sert au rapport.
    # ⚠️ REFONTE DU 2026-09-26 (phase 7 du plan de credibilite) -- LA GRAVITE
    # MESURE L'IMPACT, PLUS LA PROPAGATION. Deux raisons, mesurees :
    #
    # 1. L'echelle s'etait effondree une QUATRIEME fois (34/34 `medium`) :
    #    ransomware.live a retire le champ `infostealer` dont dependait HIGH.
    #    Il faut un critere que nous detenons pour chaque victime -- le secteur
    #    (`activity`, renseigne pour 29 alertes sur 34).
    #
    # 2. « frais ET corrobore -> CRITICAL » allait devenir une constante des
    #    que la collecte frequente (toutes les 3 h, meme jour) alimenterait des
    #    victimes NOUVELLES : les agregateurs indexent en quelques heures
    #    (mesure d'avance du 2026-09-26 : 0 victime vue avant eux), donc presque
    #    toute victime fraiche serait corroboree, donc CRITICAL. La
    #    corroboration repond a « notre lecture est-elle juste ? » -- c'est
    #    l'axe CREDIBILITE (credibility.py), qui ne se melange pas a celui-ci.
    #
    # Echelle : CRITICAL = incident frais ET secteur critique · HIGH = secteur
    # critique · MEDIUM = le reste. L'exposition d'identifiants d'employes
    # reste un levier equivalent au secteur si la donnee revient.
    # Repartition simulee sur les 34 alertes reelles : voir CONTRIBUTING.md §6.
    critique = critical_sector or privileged_credential_exposure
    if incident_is_fresh and critique:
        return AlertSeverity.CRITICAL
    # ⚠️ EXPOSITION PRIVILEGIEE = des identifiants d'EMPLOYES de
    # l'organisation figurent dans des logs de voleurs (voir
    # enrich/ransomware_live.VictimIntel.privileged_exposure). C'est un chemin
    # d'intrusion actif, pas une revendication.
    #
    # ⚠️ La distinction employe / client porte sur le ROLE vis-a-vis de
    # l'organisation, JAMAIS sur la personne : « citoyen simple » ne doit pas
    # devenir un axe de gravite (precedent DOXBYTE, desactive le 2026-08-26).
    # Et ce sont des COMPTEURS -- on ne detient aucun identifiant (regle 2).
    #
    # Repartition obtenue sur les 33 alertes reelles : **14 HIGH, 19 MEDIUM**
    # (58 % au niveau dominant), contre 73 % avant et 94 % avec la variante
    # rejetee. Les autres variantes essayees donnaient 61 %, 64 % et 97 %.
    if critique:
        return AlertSeverity.HIGH
    # ⚠️ `validated` n'eleve la severite QUE sur les types ou il resulte d'une
    # verification reelle (Luhn pour `card`, mod-97 pour `iban`). Ailleurs le
    # drapeau ne mesure rien : mesure du 2026-09-04 -- `organization` est
    # valide a **100 %** (2414/2414) et `domain` a 13 %, ces 13 % etant
    # exclusivement des `.onion` (« format reconnu », pas « fait confirme »).
    #
    # Sans cette restriction, rendre `organization` rattachable faisait passer
    # TOUTE victime nommee en HIGH d'un coup -- meme mecanisme que les 401
    # `.onion` promus HIGH le 2026-09-01 des qu'un filtre amont avait saute.
    # Elargir un calcul reveille les branches dormantes.
    if detection.validated and detection.type in _CRITICAL_TYPES:
        return AlertSeverity.CRITICAL
    return AlertSeverity.MEDIUM


def should_alert(severity: AlertSeverity) -> bool:
    """True si `severity` atteint le seuil de generation d'alerte
    (ALERT_THRESHOLD)."""
    return _SEVERITY_ORDER.index(severity) >= _SEVERITY_ORDER.index(ALERT_THRESHOLD)


def detections_to_alert(
    detections: list[DetectionContract],
) -> list[tuple[DetectionContract, AlertSeverity]]:
    """Filtre `detections` sur celles qui depassent ALERT_THRESHOLD, avec leur
    severite calculee. Ne fait aucun regroupement par entite/incident (voir
    contracts/alert.py) : c'est la responsabilite de l'appelant (futur
    service d'orchestration, voir CONTRIBUTING.md §3.3 -- pipeline/ reste pur)."""
    scored = [(d, severity_for_detection(d)) for d in detections]
    return [(d, severity) for d, severity in scored if should_alert(severity)]
