import logging

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.roles import TOUS
from app.api.deps import exige_role, get_db
from app.contracts.detection import DetectionContract, DetectionType
from app.pipeline.alerting.matching import matchable_detection_types
from app.pipeline.detect.infrastructure import is_infrastructure_domain
from app.pipeline.enrich.geo import continent_for_country, locate_domain
from app.pipeline.alerting.summary import EntitySummary, summarize_entity
from app.pipeline.collect.source_naming import group_display_name
from app.pipeline.enrich.ransomlook_corroboration import gang_slug_for_source
from app.repositories.detection_repo import DetectionRepository
from app.repositories.entity_repo import EntityRepository, to_entity_contract
from app.repositories.stats_repo import StatsRepository
from app.services.governance_report_service import rapport_direction_pdf
from app.services.governance_service import bornes_du_mois, governance
from app.services.threat_actor_service import threat_actors

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/stats", tags=["stats"], dependencies=[Depends(exige_role(TOUS))]
)

# matching.py ne peut rattacher une detection a une entite que via les types
# DOMAIN/EMAIL (seuls types avec un SelectorType equivalent, voir
# pipeline/alerting/matching.py) -- charger uniquement ces types suffit pour
# le croisement et evite de charger inutilement les ~1000 autres detections
# (volume/phone/card/iban/credentials/crypto_wallet/api_key) qui ne
# matcheront jamais.

# Le croisement se fait en memoire (voir summarize_entity), pas en SQL --
# limite haute pour ne pas tronquer silencieusement le corpus reel (5503
# detections au total, ~4565 DOMAIN+EMAIL au 2026-08-04). A revisiter si le
# volume grossit significativement (voir CONTRIBUTING.md §6 -- non prioritaire tant
# que le worker Celery/la collecte planifiee ne sont pas en place).
_MAX_DETECTIONS_LOADED = 20_000


class EntitiesStatsResponse(BaseModel):
    model_config = {"extra": "forbid"}

    entities: list[EntitySummary]


_to_entity_contract = to_entity_contract


def _to_detection_contract(detection) -> DetectionContract:
    return DetectionContract(
        id=detection.id,
        document_id=detection.document_id,
        type=detection.type,
        value_masked=detection.value_masked,
        value_hash=detection.value_hash,
        validated=detection.validated,
        is_relevant=detection.is_relevant,
        created_at=detection.created_at,
    )


@router.get("/entities", response_model=EntitiesStatsResponse)
def entities_stats(db: Session = Depends(get_db)) -> EntitiesStatsResponse:
    """Vue d'ensemble par entite surveillee : detections rattachees (voir
    pipeline/alerting/matching.py), reparties par type et severite (voir
    rules.py). Reporting/analyse, ne persiste rien (contracts/alert.py reste
    non branche sur une table, voir CONTRIBUTING.md §6)."""
    entities = [_to_entity_contract(e) for e in EntityRepository(db).list_active()]

    # Filtrage EN SQL (voir alerting/matching.py::MATCHABLE_DETECTION_TYPES) :
    # charger tous les types puis les ecarter en memoire faisait consommer le
    # plafond par des lignes jetees aussitot -- au 2026-09-01, 12 319 des
    # 20 513 detections du corpus, soit 61 % du budget.
    rows = DetectionRepository(db).list_all(
        limit=_MAX_DETECTIONS_LOADED, types_=matchable_detection_types(entities)
    )
    if len(rows) == _MAX_DETECTIONS_LOADED:
        logger.warning(
            "stats.entities: plafond de %s detections atteint -- les chiffres "
            "affiches sont tronques (tri created_at DESC).",
            _MAX_DETECTIONS_LOADED,
        )
    matchable_detections = [_to_detection_contract(d) for d in rows]

    summaries = [summarize_entity(entity, matchable_detections) for entity in entities]
    summaries.sort(key=lambda s: s.total_detections, reverse=True)

    return EntitiesStatsResponse(entities=summaries)


class CountryStat(BaseModel):
    model_config = {"extra": "forbid"}

    country_code: str
    continent: str
    victim_domains: int


class ContinentStat(BaseModel):
    model_config = {"extra": "forbid"}

    continent: str
    victim_domains: int


class GeographyResponse(BaseModel):
    model_config = {"extra": "forbid"}

    # Domaines de victimes distincts, infrastructure exclue.
    total_victim_domains: int
    # Ceux dont le domaine porte un indice de pays exploitable.
    located_victim_domains: int
    # Les autres : gTLD (.com/.net/.org), aucun indice de pays. Ce n'est PAS
    # un pays « inconnu » et cela ne doit jamais apparaitre comme une zone sur
    # une carte.
    undetermined_victim_domains: int
    countries: list[CountryStat]
    continents: list[ContinentStat]


@router.get("/geography", response_model=GeographyResponse)
def geography_stats(db: Session = Depends(get_db)) -> GeographyResponse:
    """Repartition geographique des organisations victimes, deduite du domaine.

    ⚠️ COUVERTURE PARTIELLE ET STRUCTURELLEMENT BIAISEE -- a exposer, jamais a
    masquer. Mesure du 2026-09-02 : 71 % des domaines de victimes sont des
    gTLD et ne portent aucun indice de pays. L'Amerique du Nord parait donc
    faible (78 domaines) alors que ses organisations sont simplement en
    `.com`. Une carte issue de ces donnees montre « les pays identifiables »,
    pas « les pays touches ».

    Calcul a la volee plutot que persiste : le module `enrich/geo.py` est pur
    et la table des ccTLD evoluera (chaque generique mal attribue est un pays
    fantome sur la carte). Une valeur figee en base deviendrait fausse en
    silence au premier ajustement.
    """
    rows = DetectionRepository(db).list_all(
        limit=_MAX_DETECTIONS_LOADED, types_=[DetectionType.DOMAIN.value]
    )
    if len(rows) == _MAX_DETECTIONS_LOADED:
        logger.warning(
            "stats.geography: plafond de %s detections atteint -- la carte est "
            "incomplete.",
            _MAX_DETECTIONS_LOADED,
        )

    # Sur les domaines DISTINCTS : une victime citee dans 40 annonces reste une
    # victime. Compter les detections ferait de la repetition un volume.
    domains = {
        row.value_masked
        for row in rows
        if row.value_masked and not is_infrastructure_domain(row.value_masked)
    }

    by_country: dict[str, int] = {}
    by_continent: dict[str, int] = {}
    undetermined = 0
    for domain in domains:
        country, continent = locate_domain(domain)
        if country is None or continent is None:
            undetermined += 1
            continue
        by_country[country] = by_country.get(country, 0) + 1
        by_continent[continent] = by_continent.get(continent, 0) + 1

    countries = sorted(
        (
            CountryStat(
                country_code=code,
                continent=continent_for_country(code) or "",
                victim_domains=count,
            )
            for code, count in by_country.items()
        ),
        key=lambda c: (-c.victim_domains, c.country_code),
    )
    continents = sorted(
        (
            ContinentStat(continent=name, victim_domains=count)
            for name, count in by_continent.items()
        ),
        key=lambda c: (-c.victim_domains, c.continent),
    )

    return GeographyResponse(
        total_victim_domains=len(domains),
        located_victim_domains=len(domains) - undetermined,
        undetermined_victim_domains=undetermined,
        countries=countries,
        continents=continents,
    )


class ActiviteRecente(BaseModel):
    """Ce qui est NOUVEAU et ce qui attend l'analyste.

    ⚠️ Le tableau de bord comptait sans prioriser (« 3 283 documents, 12 145
    detections, 24 sources »). Un analyste qui arrive le matin veut savoir ce
    qui a change depuis hier et ce qu'il a a traiter, pas la taille du corpus.
    """

    model_config = {"extra": "forbid"}

    depuis: datetime
    nouvelles_alertes: int
    nouvelles_alertes_graves: int
    nouveaux_documents: int
    nouvelles_detections: int
    # File de travail : ce qui attend, tous jours confondus.
    alertes_ouvertes: int
    alertes_non_affectees: int
    alertes_sans_resume: int
    # ⚠️ Trou structurel rendu visible : une entite active sans selecteur ne
    # peut JAMAIS produire d'alerte.
    entites_sans_selecteur: int
    sources_en_echec: int


@router.get("/activity", response_model=ActiviteRecente)
def activite(
    db: Session = Depends(get_db),
    heures: int = Query(default=24, ge=1, le=720, description="Fenetre de nouveaute"),
) -> ActiviteRecente:
    """Nouveautes et charge de travail, pour ouvrir la journee."""
    depuis = datetime.now(timezone.utc) - timedelta(hours=heures)
    return ActiviteRecente(depuis=depuis, **StatsRepository(db).activity_counts(depuis))


class GroupCountry(BaseModel):
    model_config = {"extra": "forbid"}

    country_code: str
    continent: str
    victim_domains: int


class GroupStat(BaseModel):
    """Un groupe attaquant : combien de victimes, et où il frappe."""

    model_config = {"extra": "forbid"}

    source_id: uuid.UUID
    # Nom nettoyé du gang. ⚠️ Les suffixes techniques du nom de source
    # (« (DLS) », « (New Dark mirror 1) ») ne veulent rien dire pour un
    # analyste et masquent le nom du groupe.
    name: str
    source_name: str
    # Identifiant du gang chez les agrégateurs (`gang_slug_for_source`) : relie
    # ce groupe au classement « qui attaque quelle région ».
    gang_slug: str | None = None
    active: bool
    victim_domains: int
    located_victim_domains: int
    countries: list[GroupCountry]
    continents: list[ContinentStat]
    # Publication la plus récente attribuée à ce groupe, quand les documents
    # portent une date. `null` = ce site ne date pas ses annonces (c'est le cas
    # de plusieurs DLS), PAS « inactif ».
    last_published_at: datetime | None
    last_collected_at: datetime | None
    # Victimes que RansomLook attribue au même groupe : une seconde lecture,
    # indépendante de la nôtre.
    corroborated_domains: int


class GroupsResponse(BaseModel):
    model_config = {"extra": "forbid"}

    groups: list[GroupStat]
    # Rappel du biais, à afficher : la carte montre les pays identifiables,
    # jamais tous les pays touchés.
    undetermined_victim_domains: int


@router.get("/groups", response_model=GroupsResponse)
def groups_stats(db: Session = Depends(get_db)) -> GroupsResponse:
    """Groupes attaquants les plus actifs, et où ils frappent.

    ⚠️ Ne compte QUE les sources qui publient leurs victimes (sites de fuite
    de gangs) : sur un forum, un domaine cité n'est pas une victime de celui
    qui l'héberge. Même autorité que partout ailleurs,
    `detect/announcement_filter.source_publishes_victims`.

    ⚠️ Sur les domaines DISTINCTS : une victime citée dans 40 annonces reste
    une victime. Compter les détections ferait de la répétition un volume.

    ⚠️ MÊME BIAIS GÉOGRAPHIQUE QUE `/geography`, et il doit être affiché :
    ~70 % des domaines sont des gTLD sans indice de pays. « 23 pays » signifie
    « 23 pays identifiables », pas « 23 pays touchés ».
    """
    from app.pipeline.detect.announcement_filter import source_publishes_victims

    lignes = StatsRepository(db).detections_with_document_and_source(
        DetectionType.DOMAIN.value, _MAX_DETECTIONS_LOADED
    )

    par_source: dict = {}
    indetermines: set[str] = set()
    for detection, document, source in lignes:
        if not source_publishes_victims(document.collector):
            continue
        valeur = (detection.value_masked or "").lower()
        if not valeur or valeur.endswith(".onion") or is_infrastructure_domain(valeur):
            continue
        etat = par_source.setdefault(
            source.id,
            {
                "source": source,
                "victimes": set(),
                "corroborees": set(),
                "publie": None,
                "collecte": None,
            },
        )
        etat["victimes"].add(valeur)
        if detection.corroboration_status == "corroborated":
            etat["corroborees"].add(valeur)
        if document.published_at and (
            etat["publie"] is None or document.published_at > etat["publie"]
        ):
            etat["publie"] = document.published_at
        if document.fetched_at and (
            etat["collecte"] is None or document.fetched_at > etat["collecte"]
        ):
            etat["collecte"] = document.fetched_at

    groupes: list[GroupStat] = []
    for etat in par_source.values():
        pays: dict[str, tuple[str, int]] = {}
        localisees = 0
        for valeur in etat["victimes"]:
            code, continent = locate_domain(valeur)
            if code is None or continent is None:
                indetermines.add(valeur)
                continue
            localisees += 1
            precedent = pays.get(code)
            pays[code] = (continent, (precedent[1] if precedent else 0) + 1)

        continents: dict[str, int] = {}
        for continent, nombre in pays.values():
            continents[continent] = continents.get(continent, 0) + nombre

        source = etat["source"]
        groupes.append(
            GroupStat(
                source_id=source.id,
                name=group_display_name(source.name),
                source_name=source.name,
                gang_slug=gang_slug_for_source(source.name),
                active=source.active,
                victim_domains=len(etat["victimes"]),
                located_victim_domains=localisees,
                countries=sorted(
                    (
                        GroupCountry(
                            country_code=code,
                            continent=continent,
                            victim_domains=nombre,
                        )
                        for code, (continent, nombre) in pays.items()
                    ),
                    key=lambda c: (-c.victim_domains, c.country_code),
                ),
                continents=sorted(
                    (
                        ContinentStat(continent=nom, victim_domains=nombre)
                        for nom, nombre in continents.items()
                    ),
                    # ⚠️ Egalites departagees par le NOM, comme `/geography`.
                    # Sans cela l'ordre dependait du parcours d'un `set` de
                    # chaines -- aleatoire d'un processus a l'autre (hachage
                    # randomise) : la carte reordonnait les continents a
                    # egalite a chaque rechargement (constate le 2026-09-25).
                    key=lambda c: (-c.victim_domains, c.continent),
                ),
                last_published_at=etat["publie"],
                last_collected_at=etat["collecte"],
                corroborated_domains=len(etat["corroborees"]),
            )
        )

    groupes.sort(key=lambda g: (-g.victim_domains, g.name, str(g.source_id)))
    return GroupsResponse(groups=groupes, undetermined_victim_domains=len(indetermines))


# --------------------------------------------------------------------------
# Gouvernance (RSSI) -- AGREGATS UNIQUEMENT, voir pipeline/reporting/governance
# --------------------------------------------------------------------------


def _mois_valide(month: str) -> str:
    try:
        bornes_du_mois(month)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Mois attendu au format AAAA-MM")
    return month


@router.get("/governance")
def governance_view(
    month: str | None = Query(
        None, description="AAAA-MM : borne l'activite du service"
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Tableau de gouvernance : activite du service (nos alertes) et menace
    sectorielle du perimetre sur 12 mois (historiques en cache, AUCUN appel
    reseau). Ouvert aux trois roles : il ne contient que des comptes."""
    return governance(db, month=_mois_valide(month) if month else None)


@router.get("/threat-actors")
def threat_actors_view(
    continent: str | None = Query(None, description="Continent, ou « Monde »"),
    country: str | None = Query(None, min_length=2, max_length=2),
    months: int = Query(12, ge=1, le=24),
    db: Session = Depends(get_db),
) -> dict:
    """Qui frappe où : classement des groupes sur une région (continent ou
    pays), d'après les historiques ransomware.live en cache. Comptes
    uniquement, aucune victime nommée : ouvert aux trois rôles."""
    return threat_actors(db, continent=continent, country=country, months=months)


@router.get("/governance/report.pdf")
def governance_report(
    month: str = Query(..., description="AAAA-MM"),
    db: Session = Depends(get_db),
):
    """Rapport mensuel de direction, deterministe (sans LLM), TLP:AMBER+STRICT.
    Agregats uniquement : il ne transporte ni nom de victime ni valeur."""
    pdf, nom = rapport_direction_pdf(db, _mois_valide(month))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )
