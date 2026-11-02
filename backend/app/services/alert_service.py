"""Orchestration : rattache les detections aux entites (pipeline/alerting/
matching.py), calcule leur severite (pipeline/alerting/rules.py), et
persiste le resultat sous forme d'Alert -- la brique qui manquait pour que
"analyse" devienne "livrable produit" (voir CONTRIBUTING.md §6 priorite n°1).

A la demande uniquement (pas de worker planifie, voir CONTRIBUTING.md) : ce
service est appele depuis un routeur API, jamais depuis une tache Celery
qui n'existe pas encore.

Regroupement : une Alert par (entite, jour) -- pas une par detection, pour
eviter de noyer l'analyste sous des alertes individuelles (voir
contracts/alert.py). Idempotent : une execution repetee le meme jour pour
la meme entite reutilise l'Alert existante et y rattache seulement les
detections pas encore liees (voir AlertRepository.add_detections), plutot
que d'en creer une nouvelle -- necessaire puisque ce service peut etre
rappele plusieurs fois par jour (ex: apres chaque nouvelle collecte)."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.contracts.alert import AlertSeverity
from app.core.config import settings
from app.contracts.detection import DetectionContract, DetectionType
from app.db.models.alert import Alert
from app.db.models.detection import Detection
from app.db.models.raw_document import RawDocument
from app.pipeline.alerting.matching import (
    value_matches_watched_entity,
    matchable_detection_types,
    matching_entities,
    most_specific,
    normalize_victim,
    victim_key,
)
from app.pipeline.alerting.effective import effective_value
from app.pipeline.alerting.rules import (
    is_critical_sector,
    severity_for_detection,
    should_alert,
)
from app.pipeline.detect.announcement_filter import source_publishes_victims
from app.pipeline.detect.infrastructure import is_infrastructure_domain
from app.pipeline.enrich.geo import continent_for_country, locate_domain
from app.pipeline.enrich.ransomlook_corroboration import CorroborationStatus
from app.repositories.alert_repo import AlertRepository
from app.repositories.detection_repo import DetectionRepository
from app.repositories.entity_repo import EntityRepository, to_entity_contract

# Meme perimetre que api/routers/stats.py : matching.py ne rattache une
# detection a une entite que via DOMAIN/EMAIL (seuls types avec un
# SelectorType equivalent) -- charger les autres types ne servirait a rien
# ici.
logger = logging.getLogger(__name__)


# Seul statut de corroboration qui eleve la severite (voir
# rules.severity_for_detection) : `exclusive` signifie « nous seuls la voyons »
# et n'est pas un doute, `unknown`/NULL est une absence de mesure. Ni l'un ni
# l'autre ne doit abaisser quoi que ce soit.
_CORROBORATED_STATUS = CorroborationStatus.CORROBORATED.value
_MAX_DETECTIONS_LOADED = 20_000

# Fenetre glissante de scan : seules les detections apparues dans les N
# derniers jours sont candidates a une alerte.
#
# Sans cette borne, generate_alerts rescannait TOUT le corpus a chaque
# execution : au changement de jour la cle de regroupement (entite, jour)
# change, donc une nouvelle alerte etait recreee sur des detections deja
# traitees la veille. Constate en usage reel -- 2 alertes identiques par jour
# (Organisation Exemple/144 et Exemple Altitudes/1, memes 145 detections datees du 17, realertees
# le 18), soit un corpus d'alertes qui grossit indefiniment sans qu'aucune
# donnee nouvelle n'apparaisse. Un analyste ne peut alors plus distinguer le
# nouveau de l'ancien, ce qui vide le livrable de sa valeur.
#
# 7 jours plutot qu'un seul : une detection reste alertable une semaine, ce
# qui laisse une marge si l'alerting n'a pas tourne un jour (worker arrete,
# panne) sans pour autant realerter indefiniment.
_ALERT_WINDOW_DAYS = 7

_SEVERITY_ORDER = [
    AlertSeverity.LOW,
    AlertSeverity.MEDIUM,
    AlertSeverity.HIGH,
    AlertSeverity.CRITICAL,
]


_to_entity_contract = to_entity_contract


def refresh_alert_severities(db, *, apply: bool = False, alert_ids=None) -> dict:
    """Recalcule la severite des alertes DEJA creees.

    ⚠️ Sans cette passe, un changement de taxonomie n'a d'effet que
    PROSPECTIF : `generate_alerts` ne porte que des detections nouvelles, si
    bien qu'une alerte existante garde a jamais la severite calculee le jour de
    sa creation. C'est ce qui avait rendu le correctif du 2026-09-01 invisible
    sur les 120 alertes de l'epoque.

    ⚠️ SIMULATION PAR DEFAUT (`apply=False`) : sur une modification de donnees,
    calculer et ecrire restent deux gestes distincts.

    ⚠️ Ne fait que MONTER ou DESCENDRE une valeur calculee ; ne touche ni au
    `status` ni au `summary`, qui portent des decisions d'analyste.

    ⚠️ `alert_ids` BORNE LA PORTEE -- ajoute le 2026-09-15 apres que le piege
    se soit produit pour la QUATRIEME fois. Un test d'integration a appele
    cette fonction avec `apply=True` pour verifier la montee en gravite d'UNE
    alerte : elle a reecrit la severite des **33 alertes reelles** de la base
    de developpement, sans erreur ni signal. Meme famille que la passe
    regionale qui ignorait `entity_ids` et avait cree une vraie alerte de
    20 victimes (2026-09-02).

    La discipline des appelants ne suffit pas : c'est la fonction qui doit
    pouvoir etre bornee. Sans `alert_ids`, la portee reste TOUTE la table,
    ce qui est le bon defaut pour la passe de production.
    """
    from app.db.models.alert import Alert, AlertDetection

    requete = (
        db.query(Alert, Detection)
        .join(AlertDetection, AlertDetection.alert_id == Alert.id)
        .join(Detection, Detection.id == AlertDetection.detection_id)
    )
    if alert_ids is not None:
        requete = requete.filter(Alert.id.in_(list(alert_ids)))
    lignes = requete.all()
    if not lignes:
        return {"examinees": 0, "modifiees": 0, "applique": apply, "details": []}

    rows = [detection for _, detection in lignes]
    revendiques = _documents_de_source_publiant_des_victimes(db, rows)
    avec_volume = _documents_annoncant_un_volume(db, rows)

    # ⚠️ Les renseignements par victime vivent sur l'ALERTE (migration 0026),
    # pas sur la detection : ils sont resolus par victime, et une alerte
    # regroupe les detections d'une meme organisation. C'est aussi pourquoi
    # cette passe est le SEUL endroit ou la nouvelle echelle s'applique
    # pleinement -- `generate_alerts` cree l'alerte avant que les
    # renseignements soient connus (ordre : generer -> corroborer ->
    # renseigner -> recalculer).
    from app.services.victim_intel_service import incident_is_fresh

    par_alerte: dict = {}
    for alerte, detection in lignes:
        # ⚠️ `intel_refreshed_at` NULL = jamais mesure. Un `compromised_employees`
        # a NULL ou 0 sans mesure ne doit PAS se lire « aucune exposition » :
        # sans cette garde, une panne de l'enrichisseur ferait silencieusement
        # retomber des alertes HIGH en MEDIUM.
        mesure = alerte.intel_refreshed_at is not None
        severite = severity_for_detection(
            _to_detection_contract(detection),
            matches_watched_entity=True,
            corroborated=detection.corroboration_status == _CORROBORATED_STATUS,
            victim_published_by_attacker=detection.document_id in revendiques,
            announced_volume=detection.document_id in avec_volume,
            incident_is_fresh=incident_is_fresh(alerte.victim_attack_date),
            privileged_credential_exposure=bool(
                mesure and (alerte.compromised_employees or 0) > 0
            ),
            critical_sector=is_critical_sector(alerte.victim_sector),
        )
        par_alerte.setdefault(alerte, []).append(severite)

    details = []
    for alerte, severites in par_alerte.items():
        calculee = _highest_severity(severites).value
        # ⚠️ Une gravite CORRIGEE par l'analyste n'est jamais ecrasee : seule la
        # valeur calculee suit le calcul (migration 0033).
        effective = effective_value(alerte.severity_override, None, calculee)
        if apply and alerte.computed_severity != calculee:
            alerte.computed_severity = calculee
        if effective == alerte.severity:
            continue
        details.append(
            {"alert_id": str(alerte.id), "avant": alerte.severity, "apres": effective}
        )
        if apply:
            alerte.severity = effective
    if apply:
        db.commit()
    return {
        "examinees": len(par_alerte),
        "modifiees": len(details),
        "applique": apply,
        "details": details,
    }


def _documents_de_source_publiant_des_victimes(db, rows) -> set:
    """Documents issus d'une source qui PUBLIE ses victimes (site de fuite).

    ⚠️ Une detection ignore d'ou elle vient : le collecteur est porte par le
    document. On resout donc document -> collecteur en UNE requete groupee ;
    une requete par detection ferait N+1 sur un scan de plusieurs milliers de
    lignes.

    ⚠️ La liste des collecteurs concernes n'est PAS redefinie ici :
    `detect/announcement_filter.source_publishes_victims` en est la seule
    autorite. La reecrire ferait diverger deux definitions du meme fait --
    exactement ce qui etait arrive aux domaines d'infrastructure, ecrits a
    trois endroits avec des variantes.
    """
    document_ids = {row.document_id for row in rows}
    if not document_ids:
        return set()
    collecteur_par_document = dict(
        db.query(RawDocument.id, RawDocument.collector)
        .filter(RawDocument.id.in_(list(document_ids)))
        .all()
    )
    return {
        doc_id
        for doc_id, collecteur in collecteur_par_document.items()
        if source_publishes_victims(collecteur)
    }


def _documents_annoncant_un_volume(db, rows) -> set:
    """Documents portant une detection `volume` NON NULLE.

    ⚠️ Le critere n'est pas la taille mais le fait d'avoir CHIFFRE la
    revendication : un gang qui annonce « 490 Go exfiltres » affirme plus que
    celui qui se contente de nommer l'organisation. Mesure du 2026-09-04 : ce
    critere partage la population des victimes revendiquees (22 documents sur
    51), la seule qui le fasse -- la fraicheur n'en separe qu'une sur 31.

    ⚠️ Un volume NUL est ecarte : `value_masked` porte une grandeur normalisee,
    et « 0 enregistrements » est un artefact d'extraction, pas une
    revendication.
    """
    document_ids = {row.document_id for row in rows}
    if not document_ids:
        return set()
    volumes = (
        db.query(Detection.document_id, Detection.value_masked)
        .filter(
            Detection.document_id.in_(list(document_ids)),
            Detection.type == DetectionType.VOLUME.value,
        )
        .all()
    )
    return {
        doc_id
        for doc_id, valeur in volumes
        if any(caractere in "123456789" for caractere in (valeur or ""))
    }


def _to_detection_contract(detection: Detection) -> DetectionContract:
    return DetectionContract(
        id=detection.id,
        document_id=detection.document_id,
        type=DetectionType(detection.type),
        value_masked=detection.value_masked,
        value_hash=detection.value_hash,
        validated=detection.validated,
        is_relevant=detection.is_relevant,
        created_at=detection.created_at,
    )


def _highest_severity(severities: list[AlertSeverity]) -> AlertSeverity:
    return max(severities, key=_SEVERITY_ORDER.index)


def generate_alerts(
    db: Session,
    *,
    today: date | None = None,
    entity_ids: list[uuid.UUID] | None = None,
    window_days: int | None = None,
    regions: list[str] | None = None,
) -> list[Alert]:
    """Scanne les detections matchables (DOMAIN/EMAIL) *recentes* contre les
    entites actives, regroupe celles qui depassent le seuil d'alerte par
    (entite, jour), et persiste/met a jour l'Alert correspondante.

    `entity_ids` restreint le scan a ces entites precises quand fourni (utilise
    par les tests pour ne pas toucher aux entites reelles de la base) ; `None`
    (defaut, usage normal depuis l'API) scanne toutes les entites actives.

    `window_days` borne l'anciennete des detections scannees (defaut
    _ALERT_WINDOW_DAYS). C'est ce qui empeche de realerter indefiniment sur
    un corpus fige : sans cette borne, chaque nouveau jour recreait la meme
    alerte sur les memes detections anciennes. Passer 0 desactive la borne
    (rescan complet) -- utile pour un rattrapage manuel, jamais pour
    l'execution planifiee.

    Retourne les Alert creees ou mises a jour lors de cet appel (pas
    l'integralite des alertes existantes)."""
    alert_date = today or datetime.now(timezone.utc).date()
    effective_window = _ALERT_WINDOW_DAYS if window_days is None else window_days

    entity_repo = EntityRepository(db)
    detection_repo = DetectionRepository(db)
    alert_repo = AlertRepository(db)

    active_entities = entity_repo.list_active()
    if entity_ids is not None:
        wanted = set(entity_ids)
        active_entities = [e for e in active_entities if e.id in wanted]
    entities = [_to_entity_contract(e) for e in active_entities]

    # Passe regionale : decidee ICI, avant toute sortie anticipee. ⚠️
    # Restreindre le scan a des entites precises (`entity_ids`) la DESACTIVE
    # par defaut : une alerte regionale n'a pas de perimetre d'entite, et la
    # laisser tourner ferait ecrire un appel volontairement restreint --
    # typiquement un test -- sur tout le corpus. Constate le 2026-09-02 : la
    # suite de tests a cree une vraie alerte regionale de 20 victimes en base.
    # Passer `regions` explicitement force la passe.
    effective_regions = regions
    if effective_regions is None:
        effective_regions = [] if entity_ids is not None else _watched_continents()

    # ⚠️ Ne sortir que si AUCUNE passe n'a de travail. L'ancien
    # `if not entities: return []` sortait AVANT la passe regionale : une
    # installation sans entite surveillee (ou toutes desactivees) ne produisait
    # JAMAIS d'alerte regionale -- precisement la fonctionnalite qui signale
    # les victimes NON declarees. Invisible en developpement (40 entites en
    # base), revele par la CI sur base vierge (2026-09-25).
    if not entities and not effective_regions:
        return []

    # Borne basse du scan : calculee depuis `alert_date` (et non `now()`) pour
    # que le comportement reste deterministe quand `today` est force -- les
    # tests et un rattrapage manuel doivent pouvoir rejouer une journee passee.
    created_from = None
    if effective_window > 0:
        created_from = datetime.combine(
            alert_date - timedelta(days=effective_window),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )

    # Filtrage des types EN SQL (voir matching.py::MATCHABLE_DETECTION_TYPES
    # pour la mesure complete) : charger tous les types puis les ecarter en
    # memoire faisait consommer le plafond par des detections inutilisables
    # ici. Au 2026-09-01, 20 513 detections dans la fenetre pour seulement
    # 8 194 matchables -- le scan s'arretait a 8 001 d'entre elles.
    rows = detection_repo.list_all(
        limit=_MAX_DETECTIONS_LOADED,
        # `organization` ne s'ajoute que si une entite declare un selecteur
        # `keyword` (voir matching.matchable_detection_types) : sinon ce serait
        # 2414 lignes de plafond pour zero alerte de plus.
        types_=matchable_detection_types(entities),
        created_from=created_from,
    )
    if len(rows) == _MAX_DETECTIONS_LOADED:
        # Le plafond reste un plafond : il borne le travail, il ne garantit pas
        # l'exhaustivite. Le franchir en silence est ce qui a rendu la perte
        # ci-dessus invisible pendant des semaines -- on le dit desormais.
        logger.warning(
            "alerts.generate: plafond de %s detections atteint (tri created_at "
            "DESC) -- les plus anciennes de la fenetre sont hors scan. "
            "Paginer ou reduire la fenetre.",
            _MAX_DETECTIONS_LOADED,
        )
    matchable_detections = [_to_detection_contract(d) for d in rows]

    # La corroboration ne fait pas partie du DetectionContract (voir
    # CONTRIBUTING.md §3.2 : ne pas modifier un contrat reel sans raison forte) --
    # elle est portee ici comme `matches_watched_entity`, en argument calcule
    # par l'appelant. On la releve sur les lignes SQL, seules a la connaitre.
    corroborated_ids = {
        d.id for d in rows if d.corroboration_status == _CORROBORATED_STATUS
    }

    # Valeur de chaque detection, pour le dedoublonnage par victime.
    victim_by_detection = {row.id: (row.value_masked or "") for row in rows}

    # ⚠️ Une detection ne sait pas d'ou elle vient : le collecteur est porte par
    # le DOCUMENT. On le releve en UNE requete groupee plutot qu'une par
    # detection, et on le passe en argument calcule -- meme patron que la
    # corroboration, pour ne pas modifier `DetectionContract` (CONTRIBUTING.md §3.2).
    documents_revendiques = _documents_de_source_publiant_des_victimes(db, rows)
    documents_avec_volume = _documents_annoncant_un_volume(db, rows)

    # entity_id -> liste de (detection_id, severity) a alerter
    #
    # La severite est calculee APRES le matching, pas avant : le rattachement a
    # une entite surveillee est lui-meme un critere de pertinence (voir
    # rules.severity_for_detection, argument `matches_watched_entity`). Une
    # detection non rattachee n'a de toute facon pas d'alerte a produire.
    to_alert: dict[uuid.UUID, list[tuple[uuid.UUID, AlertSeverity]]] = {}
    for detection in matchable_detections:
        matched = most_specific(matching_entities(detection, entities))
        if not matched:
            continue
        severity = severity_for_detection(
            detection,
            matches_watched_entity=True,
            corroborated=detection.id in corroborated_ids,
            victim_published_by_attacker=(
                detection.document_id in documents_revendiques
            ),
            announced_volume=detection.document_id in documents_avec_volume,
        )
        if not should_alert(severity):
            continue
        for entity in matched:
            to_alert.setdefault(entity.id, []).append((detection.id, severity))

    updated_alerts: list[Alert] = []
    for entity_id, scored_detections in to_alert.items():
        # ⚠️ Ne realerter QUE sur des detections nouvelles.
        #
        # L'unicite d'une alerte est posee sur (entite, jour) : sans ce
        # filtre, une entite dont les detections n'ont pas change recevait
        # une alerte identique chaque jour, puisque celle de la veille porte
        # une autre date. Mesure du 2026-08-29 : 120 alertes pour 30
        # organisations apres quatre jours -- un facteur qui augmentait d'une
        # unite par jour et aurait rendu l'interface inexploitable.
        #
        # Une alerte signifie donc desormais « quelque chose de NOUVEAU s'est
        # produit ce jour-la » et non « cette entite est toujours concernee ».
        already_alerted = alert_repo.alerted_detection_ids(entity_id)
        # Dedoublonnage par VICTIME en plus de l'identifiant de detection : une
        # meme organisation est souvent redetectee dans un autre document ou
        # publiee par un second site de fuite (mesure du 2026-09-02 : 279
        # victimes ont plusieurs detections, 103 sont vues par plusieurs
        # sources). Sans cela, `transports-exemple.com` produisait deux alertes
        # -- une par KRYBIT, une par NIGHT SPIRE -- pour un seul incident.
        already_victims = alert_repo.alerted_victims(
            entity_id=entity_id, before=alert_date
        )
        scored_detections = [
            (d_id, sev)
            for d_id, sev in scored_detections
            if d_id not in already_alerted
            and normalize_victim(victim_by_detection.get(d_id, ""))
            not in already_victims
        ]
        if not scored_detections:
            continue

        severity = _highest_severity([s for _, s in scored_detections])
        detection_ids = [d_id for d_id, _ in scored_detections]

        alert = alert_repo.get_by_entity_and_date(entity_id, alert_date)
        if alert is None:
            alert = Alert(
                id=uuid.uuid4(),
                entity_id=entity_id,
                severity=severity.value,
                computed_severity=severity.value,
                status="open",
                alert_date=alert_date,
                created_at=datetime.now(timezone.utc),
            )
            alert = alert_repo.create(alert)
        elif _SEVERITY_ORDER.index(severity) > _SEVERITY_ORDER.index(
            AlertSeverity(alert.severity)
        ):
            # Une nouvelle detection plus severe rejoint une alerte du jour
            # deja creee avec une severite plus basse -- la severite de
            # l'alerte doit refleter le pire cas de ses detections.
            alert.computed_severity = severity.value
            if not alert.severity_override:
                alert.severity = severity.value
            alert = alert_repo.update(alert)

        alert = alert_repo.add_detections(alert, detection_ids)
        updated_alerts.append(alert)

    # Passe regionale (portee decidee en tete de fonction).
    if effective_regions:
        updated_alerts.extend(
            _generate_region_alerts(
                db,
                alert_repo=alert_repo,
                rows=rows,
                corroborated_ids=corroborated_ids,
                alert_date=alert_date,
                continents=effective_regions,
                created_from=created_from,
            )
        )
    return updated_alerts


def _watched_continents() -> list[str]:
    return [
        c.strip() for c in settings.ALERT_WATCHED_CONTINENTS.split(",") if c.strip()
    ]


def _generate_region_alerts(
    db: Session,
    *,
    alert_repo: AlertRepository,
    rows: list[Detection],
    corroborated_ids: set[uuid.UUID],
    alert_date: date,
    continents: list[str],
    created_from: datetime | None = None,
) -> list[Alert]:
    """Alerte sur une victime située dans un perimetre GEOGRAPHIQUE surveille,
    meme si aucune entite ne la declare (voir migration 0016).

    Repond au goulot mesure le 2026-09-02 : 3101 domaines de victimes
    collectes, 31 surveilles -- 1 % de conversion. Le blocage n'etait plus la
    collecte mais la declaration.

    ⚠️ RESTREINT AUX SOURCES QUI PUBLIENT DES VICTIMES, et ce n'est pas une
    precaution de principe : sans cette contrainte, la mesure donne 7 domaines
    africains non surveilles dont **4 faux positifs** -- `breachforums.bf` (le
    forum lui-meme), `gilber.t.sc` et `juarez.sc` (des phrases decoupees en
    domaines), et deux organisations simplement CITEES dans un document
    intitule « 179 major companies in the world 2026 ». Etre nomme dans une
    liste n'est pas etre victime.

    Avec la contrainte : 20 domaines africains, tous de vraies organisations,
    zero artefact. La watchlist ne faisait donc pas que cadrer le perimetre,
    elle filtrait aussi la qualite -- une alerte regionale doit reconstituer ce
    filtre autrement.
    """
    # TOUTES les entites actives, jamais un sous-ensemble : cette liste sert a
    # ecarter les victimes deja couvertes par une alerte nominative. Avec une
    # liste tronquee, les 18 victimes africaines deja surveillees se
    # retrouvaient dupliquees dans l'alerte regionale (constate).
    entities = [_to_entity_contract(e) for e in EntityRepository(db).list_active()]

    # Un document par victime : c'est ce qui rend le domaine du titre fiable.
    #
    # Le collecteur de chaque document est charge en UNE requete groupee. Un
    # cache attache a la fonction persisterait entre les appels et deviendrait
    # faux des qu'un document change de source.
    publishing = _documents_de_source_publiant_des_victimes(db, rows)
    documents_avec_volume = _documents_annoncant_un_volume(db, rows)

    valeur_par_detection = {row.id: (row.value_masked or "") for row in rows}
    by_region: dict[str, list[tuple[uuid.UUID, AlertSeverity]]] = {}
    for row in rows:
        if row.document_id not in publishing:
            continue
        value = row.value_masked
        if not value or is_infrastructure_domain(value):
            continue
        _, continent = locate_domain(value)
        if continent not in continents:
            continue

        detection = _to_detection_contract(row)
        # ⚠️ Exclusion par VALEUR, pas par detection. Une victime deja
        # surveillee est traitee par la passe nominative ; la re-signaler ici
        # comme « non declaree » est un FAUX POSITIF, pas un doublon anodin :
        # l'alerte affirme le contraire de la verite.
        #
        # Mesure du 2026-09-04 : l'alerte regionale « Afrique -- victime non
        # declaree » portait 21 detections, **toutes** des organisations
        # surveillees (distribution-exemple.co.za, telecom-exemple.ma, egov-exemple.sc, institution-exemple.sn...). Elles
        # etaient de type `organization`, que `matching_entities` ne sait pas
        # rattacher faute de selecteur `keyword` -- alors que le MEME document
        # portait une detection `domain` qui, elle, matchait l'entite.
        if value_matches_watched_entity(value, entities):
            continue
        severity = severity_for_detection(
            detection,
            matches_watched_entity=True,
            corroborated=detection.id in corroborated_ids,
            # La passe regionale ne traite QUE des documents de sources qui
            # publient leurs victimes (filtre `publishing` ci-dessus) : le
            # drapeau y est vrai par construction.
            victim_published_by_attacker=True,
            announced_volume=row.document_id in documents_avec_volume,
        )
        if not should_alert(severity):
            continue
        by_region.setdefault(continent, []).append((detection.id, severity))

    # Victimes publiees SANS domaine localisable, dont un agregateur DECLARE
    # le pays (voir services/victim_location_service). Sans cette etape,
    # « Exemple Defence Force » ou « Exemple Risk » entraient au corpus sans
    # jamais atteindre cette passe : pas de domaine, donc pas de pays.
    for row, meta in DetectionRepository(db).with_declared_victim_country(
        created_from=created_from
    ):
        # Pas d'exclusion « deja vue par son domaine » : le service ne localise
        # QUE les documents sans domaine localisable, les deux chemins ne se
        # recouvrent donc pas (et un `.com` present ne localise rien).
        continent = continent_for_country(meta.get("victim_country"))
        if continent not in continents:
            continue
        domaine = meta.get("victim_domain") or ""
        # Meme exclusion que pour les domaines : une organisation surveillee
        # signalee comme « non declaree » serait un faux positif.
        if value_matches_watched_entity(
            row.value_masked or "", entities
        ) or value_matches_watched_entity(domaine, entities):
            continue
        detection = _to_detection_contract(row)
        severity = severity_for_detection(
            detection,
            matches_watched_entity=True,
            corroborated=False,
            victim_published_by_attacker=True,
            announced_volume=row.document_id in documents_avec_volume,
        )
        if not should_alert(severity):
            continue
        # Dedoublonnage sur le DOMAINE declare quand il existe : une victime
        # deja signalee par son domaine ne doit pas revenir par son nom.
        valeur_par_detection[row.id] = domaine or (row.value_masked or "")
        by_region.setdefault(continent, []).append((row.id, severity))

    created: list[Alert] = []
    for region, scored in by_region.items():
        already = alert_repo.alerted_detection_ids_for_region(region)
        # Meme cle que les alertes a creer (`victim_key`, qui rabat une adresse
        # sur son domaine) : sinon une victime deja signalee par une adresse
        # e-mail reviendrait le lendemain par son domaine.
        already_victims = {
            victim_key(v)
            for v in alert_repo.alerted_victims(region=region, before=alert_date)
        }
        # ⚠️ UNE ALERTE PAR VICTIME (migration 0032), plus une par (region,
        # jour). Mesure du 2026-09-30 : l'alerte « Afrique » du 29/09 portait
        # 14 victimes sous UNE gravite `medium`, et la Exemple Defence Force
        # (defense, attaque de moins de 30 jours, donc CRITICAL seule) y etait
        # noyee. Gravite, credibilite, Admiralty et date d'attaque sont portes
        # par l'alerte : sur un agregat, ils ne decrivaient aucune victime.
        # La cle est celle du dedoublonnage d'un jour a l'autre : une victime
        # publiee par deux sites le meme jour reste UNE alerte.
        par_victime: dict[str, list[tuple[uuid.UUID, AlertSeverity]]] = {}
        for d_id, sev in scored:
            # `valeur_par_detection` porte deja le domaine declare pour une
            # victime localisee par l'agregateur (voir plus haut).
            victime = victim_key(valeur_par_detection.get(d_id, ""))
            if not victime or d_id in already or victime in already_victims:
                continue
            par_victime.setdefault(victime, []).append((d_id, sev))

        for victime, siennes in par_victime.items():
            severity = _highest_severity([sev for _, sev in siennes])
            alert = alert_repo.get_by_region_victim_and_date(
                region, victime, alert_date
            )
            if alert is None:
                alert = alert_repo.create(
                    Alert(
                        id=uuid.uuid4(),
                        entity_id=None,
                        scope="region",
                        region=region,
                        victim_key=victime,
                        severity=severity.value,
                        computed_severity=severity.value,
                        status="open",
                        alert_date=alert_date,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            elif _SEVERITY_ORDER.index(severity) > _SEVERITY_ORDER.index(
                AlertSeverity(alert.severity)
            ):
                alert.computed_severity = severity.value
                if not alert.severity_override:
                    alert.severity = severity.value
                alert = alert_repo.update(alert)

            created.append(
                alert_repo.add_detections(alert, [d_id for d_id, _ in siennes])
            )
    return created
