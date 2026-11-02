import json
import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.roles import PEUT_ADMINISTRER, PEUT_TRAITER_LES_ALERTES
from app.pipeline.alerting.subject import region_alert_subject, region_alert_victim
from app.pipeline.reporting.governance import SECTEURS_FR
from app.services.admiralty_service import (
    rate_alerts,
    victim_claims,
    victim_titles,
)
from app.services.alert_access_service import journaliser_acces
from app.api.deps import exige_role, get_current_user, get_db
from app.api.routers.llm import get_selected_model
from app.contracts.alert import AlertSeverity, AlertStatus
from app.db.models.user import User
from app.db.models.alert import Alert
from app.services.report_service import generer_rapport_pdf, sujet_alerte
from app.core.config import settings
from app.core.llm.client import generate_response
from app.pipeline.alerting.digest import DIGEST_QUERY, build_digest_content
from app.pipeline.alerting.summarize import summarize_alert
from app.pipeline.alerting.effective import origin_of
from app.repositories.alert_repo import AlertRepository
from app.services import entity_service
from app.repositories.document_repo import RawDocumentRepository
from app.repositories.source_repo import SourceRepository
from app.repositories.entity_repo import EntityRepository
from app.services.alert_service import generate_alerts, refresh_alert_severities
from app.services.corroboration_service import corroborate_corpus
from app.services.gang_profile_service import MODUS_OPERANDI_CAVEAT, modus_operandi
from app.services.stix_export_service import exporter_stix
from app.pipeline.enrich.ttp import cve_url, mitre_technique_url

router = APIRouter(
    prefix="/api/alerts",
    tags=["alerts"],
    dependencies=[Depends(exige_role(PEUT_TRAITER_LES_ALERTES))],
)


class AlertOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    # `None` pour une alerte de perimetre geographique (migration 0016) :
    # elle signale une victime que personne n'a declaree.
    entity_id: uuid.UUID | None
    # "entity" ou "region".
    scope: str = "entity"
    # Continent surveille, renseigne uniquement quand `scope == "region"`.
    region: str | None = None
    severity: str
    status: str
    alert_date: date
    summary: str | None
    detection_count: int
    created_at: datetime

    # Corroboration par un second observateur (RansomLook). `None` = jamais
    # confronte ; ne pas l'afficher comme « non corrobore », c'est une
    # absence de mesure et non un resultat negatif.
    corroboration_status: str | None = None
    corroborated_group: str | None = None
    corroborated_count: int = 0
    corroborated_at: datetime | None = None
    # Lien public citable justifiant la corroboration (page du gang sur
    # RansomLook). Permet a l'analyste de VERIFIER, pas seulement de lire.
    corroboration_evidence_url: str | None = None
    # Tous les gangs qui revendiquent la victime, et date d'indexation la plus
    # ancienne chez RansomLook (migration 0024).
    corroborated_groups: list[str] | None = None
    corroboration_first_seen_at: datetime | None = None
    # Observateurs tiers ayant vu les victimes (ransomlook, ransomware_live).
    corroboration_observers: list[str] | None = None

    # --- Renseignements par victime (migration 0026) ------------------
    # ⚠️ AUCUNE PII : que des COMPTEURS, des DATES et des LIBELLES.
    # ⚠️ Tout ceci ne veut rien dire tant que `intel_refreshed_at` est NULL :
    # `compromised_employees = 0` se lit « mesure, et nul », NULL se lit
    # « jamais mesure ». L'interface doit distinguer les deux.
    victim_attack_date: datetime | None = None
    victim_sector: str | None = None
    victim_country: str | None = None
    compromised_employees: int | None = None
    compromised_users: int | None = None
    compromised_thirdparties: int | None = None
    stealer_families: list[str] | None = None
    last_employee_compromised: datetime | None = None
    last_user_compromised: datetime | None = None
    intel_refreshed_at: datetime | None = None

    # --- Confirmation par la presse (migration 0030) -------------------
    # Signal de CREDIBILITE (« la fuite est-elle reelle ? »). NULL = aucune
    # confirmation connue, jamais « fuite fausse ».
    press_source_url: str | None = None
    press_evidence_url: str | None = None
    press_confirmed_at: datetime | None = None

    # --- Credibilite (migration 0031) ---------------------------------
    # « La fuite est-elle reelle ? », axe DISTINCT de `severity`. NULL =
    # jamais evaluee. Voir pipeline/alerting/credibility.py.
    credibility_level: str | None = None
    credibility_evidence: str | None = None
    credibility_assessed_at: datetime | None = None
    # Notation Admiralty (A-F / 1-6), calculee A LA VOLEE -- voir
    # pipeline/alerting/admiralty.py. Chaque note porte son motif : une lettre
    # sans justification ne serait qu'une affirmation de plus.
    admiralty_code: str | None = None
    admiralty_source: str | None = None
    admiralty_source_reason: str | None = None
    admiralty_source_name: str | None = None
    admiralty_information: str | None = None
    admiralty_information_reason: str | None = None
    # Libelle lisible d'une alerte REGIONALE, qui n'a pas d'entite : nomme la
    # victime (titre du document publie par le groupe). `None` pour une alerte
    # d'entite, dont le nom vient de l'entite. Voir pipeline/alerting/subject.
    subject_label: str | None = None
    # La victime SEULE, sans le suffixe de portee (liste des alertes).
    victim_label: str | None = None
    # Secteur en francais, traduit au MEME endroit que la vue de direction
    # (`SECTEURS_FR`) : deux tables de traduction finiraient par diverger.
    victim_sector_label: str | None = None

    # Rappel demande par un analyste (migration 0017). Ne cree jamais d'alerte
    # supplementaire -- voir la route `/remind`.
    reminded_at: datetime | None = None
    reminder_count: int = 0
    # Travail d'analyste (migration 0022). ⚠️ Ces champs etaient en base mais
    # ABSENTS de la sortie jusqu'au 2026-10-02 : l'interface n'affichait ni la
    # note, ni le motif de cloture, ni les dates d'acquittement et de
    # resolution -- sans erreur, les champs arrivaient simplement absents.
    assignee: str | None = None
    analyst_note: str | None = None
    resolution_reason: str | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    # Migration 0033. Organisation et groupe, pour lire « Acme Côte
    # d'Ivoire · groupe Acme » sans recharger toute la liste d'entites.
    entity_name: str | None = None
    group_id: uuid.UUID | None = None
    group_name: str | None = None
    # Valeurs CALCULEES et CORRECTIONS d'analyste. L'origine de chaque valeur
    # effective est exposee : un pays sans origine ne se verifie pas.
    computed_severity: str | None = None
    computed_country: str | None = None
    computed_sector: str | None = None
    severity_override: str | None = None
    country_override: str | None = None
    sector_override: str | None = None
    override_reason: str | None = None
    override_by: str | None = None
    override_at: datetime | None = None
    severity_origin: str | None = None
    country_origin: str | None = None
    sector_origin: str | None = None

    @classmethod
    def from_model(cls, alert: Alert) -> "AlertOut":
        return cls(
            id=alert.id,
            entity_id=alert.entity_id,
            scope=alert.scope,
            region=alert.region,
            severity=alert.severity,
            status=alert.status,
            alert_date=alert.alert_date,
            summary=alert.summary,
            detection_count=len(alert.detections),
            created_at=alert.created_at,
            corroboration_status=alert.corroboration_status,
            corroborated_group=alert.corroborated_group,
            corroborated_count=alert.corroborated_count or 0,
            reminded_at=alert.reminded_at,
            reminder_count=alert.reminder_count or 0,
            assignee=alert.assignee,
            analyst_note=alert.analyst_note,
            resolution_reason=alert.resolution_reason,
            acknowledged_at=alert.acknowledged_at,
            resolved_at=alert.resolved_at,
            computed_severity=alert.computed_severity,
            computed_country=alert.computed_country,
            computed_sector=alert.computed_sector,
            severity_override=alert.severity_override,
            country_override=alert.country_override,
            sector_override=alert.sector_override,
            override_reason=alert.override_reason,
            override_by=alert.override_by,
            override_at=alert.override_at,
            corroborated_at=alert.corroborated_at,
            corroboration_evidence_url=alert.corroboration_evidence_url,
            corroborated_groups=alert.corroborated_groups,
            corroboration_first_seen_at=alert.corroboration_first_seen_at,
            corroboration_observers=alert.corroboration_observers,
            victim_attack_date=alert.victim_attack_date,
            victim_sector=alert.victim_sector,
            victim_country=alert.victim_country,
            compromised_employees=alert.compromised_employees,
            compromised_users=alert.compromised_users,
            compromised_thirdparties=alert.compromised_thirdparties,
            stealer_families=alert.stealer_families,
            last_employee_compromised=alert.last_employee_compromised,
            last_user_compromised=alert.last_user_compromised,
            intel_refreshed_at=alert.intel_refreshed_at,
            press_source_url=alert.press_source_url,
            press_evidence_url=alert.press_evidence_url,
            press_confirmed_at=alert.press_confirmed_at,
            credibility_level=alert.credibility_level,
            credibility_evidence=alert.credibility_evidence,
            credibility_assessed_at=alert.credibility_assessed_at,
        )


def _sortie(db: Session, alertes: list[Alert]) -> list[AlertOut]:
    """AlertOut + notation Admiralty, en deux requetes quel que soit le
    nombre d'alertes. Utilise par TOUTES les routes qui rendent une alerte :
    sinon la note disparaitrait de la ligne apres un changement de statut."""
    notes = rate_alerts(db, alertes)
    victimes = victim_titles(db, [a for a in alertes if a.scope == "region"])
    entites = EntityRepository(db).by_ids_with_parents(
        {a.entity_id for a in alertes if a.entity_id}
    )
    sorties = []
    for alerte in alertes:
        out = AlertOut.from_model(alerte)
        entite = entites.get(alerte.entity_id) if alerte.entity_id else None
        if entite is not None:
            out.entity_name = entite.name
            if entite.parent_id and entite.parent_id in entites:
                out.group_id = entite.parent_id
                out.group_name = entites[entite.parent_id].name
        out.severity_origin = origin_of(
            alerte.severity_override, None, alerte.computed_severity
        )
        out.country_origin = origin_of(
            alerte.country_override,
            entite.country if entite else None,
            alerte.computed_country,
        )
        out.sector_origin = origin_of(
            alerte.sector_override,
            entite.sector if entite else None,
            alerte.computed_sector,
        )
        if alerte.victim_sector:
            out.victim_sector_label = SECTEURS_FR.get(
                alerte.victim_sector, alerte.victim_sector
            )
        if alerte.scope == "region" and alerte.region:
            out.subject_label = region_alert_subject(
                alerte.region, victimes.get(alerte.id, [])
            )
            out.victim_label = region_alert_victim(victimes.get(alerte.id, []))
        note = notes.get(alerte.id)
        if note is not None:
            out.admiralty_code = note.code
            out.admiralty_source = note.source.valeur
            out.admiralty_source_reason = note.source.motif
            out.admiralty_source_name = note.source_name
            out.admiralty_information = note.information.valeur
            out.admiralty_information_reason = note.information.motif
        sorties.append(out)
    return sorties


class AlertListResponse(BaseModel):
    model_config = {"extra": "forbid"}

    total: int
    offset: int
    limit: int
    items: list[AlertOut]


class AlertStatusUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    status: AlertStatus


class GenerateAlertsResponse(BaseModel):
    model_config = {"extra": "forbid"}

    created_or_updated: list[AlertOut]


@router.get("", response_model=AlertListResponse)
def list_alerts(
    db: Session = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
    status: AlertStatus | None = None,
    entity_id: uuid.UUID | None = None,
    severity: Annotated[list[AlertSeverity] | None, Query()] = None,
    alert_date: date | None = None,
    group_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> AlertListResponse:
    # ⚠️ `list` est journalisee autant que `read` : la file expose deja des
    # noms d'organisations victimes, pas seulement des identifiants.
    journaliser_acces(db, utilisateur, "list")
    """Alertes, filtrables par statut, entite, SEVERITE et journee.

    ⚠️ `severity` est repetable (`?severity=high&severity=medium`) et filtre
    EN SQL : le total doit suivre le filtre, sinon la pagination annonce plus
    d'alertes qu'elle n'en sert -- meme defaut que le filtre
    `announcement_class` des documents, corrige le 2026-09-02.
    """
    repo = AlertRepository(db)
    status_value = status.value if status is not None else None
    severites = [s.value for s in severity] if severity else None
    alerts = repo.list(
        offset=offset,
        limit=limit,
        status=status_value,
        entity_id=entity_id,
        severities=severites,
        alert_date=alert_date,
        group_id=group_id,
    )
    total = repo.count(
        status=status_value,
        entity_id=entity_id,
        severities=severites,
        alert_date=alert_date,
        group_id=group_id,
    )
    return AlertListResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=_sortie(db, list(alerts)),
    )


class AlertDatesResponse(BaseModel):
    model_config = {"extra": "forbid"}

    dates: list[date]


# ⚠️ DOIT etre declaree AVANT `/{alert_id}` : FastAPI resout dans l'ordre de
# declaration, et `/{alert_id}` capturerait « dates » puis echouerait a le lire
# comme un UUID (422).
@router.get("/dates", response_model=AlertDatesResponse)
def list_alert_dates(db: Session = Depends(get_db)) -> AlertDatesResponse:
    """Journees qui portent au moins une alerte, de la plus recente a la plus
    ancienne.

    Sert a proposer un choix de journee REEL : un calendrier libre ferait
    tomber l'analyste sur des jours vides sans qu'il sache lesquels sont
    peuples.
    """
    return AlertDatesResponse(dates=AlertRepository(db).dates_disponibles())


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(
    alert_id: uuid.UUID,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> AlertOut:
    alert = AlertRepository(db).get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    # Journalise APRES le 404 : tracer un acces a une alerte inexistante
    # polluerait le journal sans rien prouver.
    journaliser_acces(db, utilisateur, "read", alert_id=alert_id)
    return _sortie(db, [alert])[0]


class ResolutionReason(str, Enum):
    """Pourquoi une alerte est close.

    ⚠️ `false_positive` est la valeur qui compte : sans elle, ecarter une
    fausse alerte est indistinguable de traiter un incident reel.
    """

    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    DUPLICATE = "duplicate"
    OUT_OF_SCOPE = "out_of_scope"


def _alerte(db: Session, alert_id: uuid.UUID) -> Alert:
    alert = AlertRepository(db).get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.patch("/{alert_id}/status", response_model=AlertOut)
def update_alert_status(
    alert_id: uuid.UUID, payload: AlertStatusUpdate, db: Session = Depends(get_db)
) -> AlertOut:
    repo = AlertRepository(db)
    alert = repo.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = payload.status.value
    # Horodatage des decisions : sans lui, on sait qu'une alerte est resolue
    # mais pas quand, donc aucun delai de traitement n'est mesurable.
    maintenant = datetime.now(timezone.utc)
    if alert.status == AlertStatus.ACKNOWLEDGED.value and alert.acknowledged_at is None:
        alert.acknowledged_at = maintenant
    if alert.status == AlertStatus.RESOLVED.value:
        alert.resolved_at = maintenant
    alert = repo.update(alert)
    return _sortie(db, [alert])[0]


class AlertTriageUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    assignee: str | None = None
    # Borne : texte libre, il finit dans le dossier, le PDF et les exports.
    analyst_note: str | None = Field(default=None, max_length=4000)
    # ⚠️ `false_positive` doit etre distinguable de `confirmed` : sans cette
    # qualification, ecarter une fausse alerte et traiter un incident reel
    # laissent le meme etat `resolved`, et l'historique des faux positifs --
    # seule matiere permettant d'ajuster les seuils plus tard -- est perdu.
    resolution_reason: ResolutionReason | None = None


class AlertCorrection(BaseModel):
    """Correction d'analyste (migration 0033). `null` sur un champ = pas de
    correction pour ce fait ; le motif est OBLIGATOIRE : une correction sans
    justification ne se relit pas, et c'est elle qui mesure le desaccord
    entre la plateforme et l'humain."""

    model_config = {"extra": "forbid"}

    severity: AlertSeverity | None = None
    country: str | None = None
    sector: str | None = None
    reason: str = Field(min_length=5, max_length=1000)


def _reappliquer(db: Session, alerte: Alert) -> Alert:
    """Pays, secteur et gravite effectifs de CETTE alerte seulement, puis
    resume efface : il decrivait les anciennes valeurs (meme regle que la
    scission des alertes regionales)."""
    from app.services.victim_intel_service import apply_effective_facts

    apply_effective_facts(db, alert_ids=[alerte.id])
    refresh_alert_severities(db, apply=True, alert_ids=[alerte.id])
    db.refresh(alerte)
    alerte.severity = (
        alerte.severity_override or alerte.computed_severity or alerte.severity
    )
    alerte.summary = None
    db.commit()
    db.refresh(alerte)
    return alerte


@router.put("/{alert_id}/correction", response_model=AlertOut)
def corriger_alerte(
    alert_id: uuid.UUID,
    payload: AlertCorrection,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> AlertOut:
    """Corrige le pays, le secteur et/ou la gravite d'une alerte. La valeur
    calculee reste conservee et affichee ; les passes automatiques ne
    touchent plus une valeur corrigee."""
    if payload.severity is None and not payload.country and not payload.sector:
        raise HTTPException(status_code=400, detail="Aucune correction indiquée.")
    try:
        pays = entity_service.normaliser_pays(payload.country)
        secteur = entity_service.normaliser_secteur(payload.sector)
    except entity_service.EntityError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    alerte = _alerte(db, alert_id)
    alerte.severity_override = payload.severity.value if payload.severity else None
    alerte.country_override = pays
    alerte.sector_override = secteur
    alerte.override_reason = payload.reason.strip()
    alerte.override_by = utilisateur.username
    alerte.override_at = datetime.now(timezone.utc)
    db.commit()
    return _sortie(db, [_reappliquer(db, alerte)])[0]


@router.delete("/{alert_id}/correction", response_model=AlertOut)
def annuler_correction(alert_id: uuid.UUID, db: Session = Depends(get_db)) -> AlertOut:
    """Retire la correction : l'alerte reprend les valeurs declarees ou
    calculees."""
    alerte = _alerte(db, alert_id)
    alerte.severity_override = None
    alerte.country_override = None
    alerte.sector_override = None
    alerte.override_reason = None
    alerte.override_by = None
    alerte.override_at = None
    db.commit()
    return _sortie(db, [_reappliquer(db, alerte)])[0]


@router.patch("/{alert_id}/triage", response_model=AlertOut)
def update_alert_triage(
    alert_id: uuid.UUID, payload: AlertTriageUpdate, db: Session = Depends(get_db)
) -> AlertOut:
    """Affectation, note d'analyste et qualification de la resolution."""
    repo = AlertRepository(db)
    alert = _alerte(db, alert_id)
    champs = payload.model_dump(exclude_unset=True)
    for nom in ("assignee", "analyst_note"):
        if nom in champs:
            setattr(alert, nom, champs[nom])
    if "resolution_reason" in champs:
        raison = champs["resolution_reason"]
        alert.resolution_reason = raison.value if raison is not None else None
    return _sortie(db, [repo.update(alert)])[0]


class DeleteAllAlertsResponse(BaseModel):
    model_config = {"extra": "forbid"}

    deleted_count: int


@router.delete(
    "",
    response_model=DeleteAllAlertsResponse,
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)
def delete_all_alerts(db: Session = Depends(get_db)) -> DeleteAllAlertsResponse:
    """Vide entierement la table des alertes (et leurs rattachements
    alert_detections) -- voir AlertRepository.delete_all. Ne touche ni aux
    detections ni aux documents/entites qui les ont produites : une alerte
    peut toujours etre regeneree via POST /generate."""
    deleted_count = AlertRepository(db).delete_all()
    return DeleteAllAlertsResponse(deleted_count=deleted_count)


@router.post("/generate", response_model=GenerateAlertsResponse, status_code=201)
def generate(
    window_days: int | None = Query(
        default=None,
        ge=0,
        description=(
            "Anciennete maximale des detections scannees, en jours. "
            "0 = aucune borne (rattrapage manuel). Par defaut : 7 jours."
        ),
    ),
    db: Session = Depends(get_db),
) -> GenerateAlertsResponse:
    """Declenche le scan des detections contre les entites actives (voir
    services/alert_service.py). Egalement planifie toutes les heures (Celery
    beat) ; cette route sert au declenchement a la demande.

    Idempotent : reutilise l'alerte du jour si elle existe deja, et ne
    re-alerte ni sur une detection ni sur une victime deja signalees.

    ⚠️ `window_days=0` desactive la fenetre glissante de 7 jours -- le
    rattrapage manuel prevu par le service. Il existe parce que vider les
    alertes n'est PAS reversible par une regeneration ordinaire : les
    detections plus anciennes que la fenetre ne peuvent plus rien produire.
    Constate le 2026-09-03 -- apres un vidage, seules 2 alertes se sont
    recreees sur 32, **6784 detections matchables sur 9382 etant deja hors
    fenetre**.
    """
    alerts = generate_alerts(db, window_days=window_days)
    return GenerateAlertsResponse(created_or_updated=_sortie(db, list(alerts)))


class CorroborationResponse(BaseModel):
    """Compte rendu d'une passe de corroboration."""

    success: bool
    feed_size: int = 0
    detections_checked: int = 0
    detections_corroborated: int = 0
    alerts_corroborated: int = 0
    error: str | None = None


@router.post("/{alert_id}/corroborate", response_model=CorroborationResponse)
def corroborate_one(
    alert_id: uuid.UUID, db: Session = Depends(get_db)
) -> CorroborationResponse:
    """Confronte les detections de CETTE alerte au flux public RansomLook
    (voir pipeline/enrich/ransomlook_corroboration.py) : un second
    observateur independant a-t-il vu la meme victime, et sous quel gang ?

    Enrichissement clearnet depuis le reseau `backend`, hors Tor -- meme
    regime que crt.sh et IntelX (voir CONTRIBUTING.md §2) : RansomLook interroge
    son propre index deja constitue, ce n'est une requete ni vers un DLS ni
    vers l'infrastructure d'une victime.

    Renvoie 200 avec `success=false` si le flux est injoignable plutot qu'une
    erreur : la corroboration est un enrichissement, son indisponibilite
    n'invalide pas l'alerte."""
    alert = AlertRepository(db).get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    outcome = corroborate_corpus(db, alert_id=alert_id)
    return CorroborationResponse(
        success=outcome.success,
        feed_size=outcome.feed_size,
        detections_checked=outcome.detections_checked,
        detections_corroborated=outcome.detections_corroborated,
        alerts_corroborated=outcome.alerts_corroborated,
        error=outcome.error,
    )


@router.post("/corroborate", response_model=CorroborationResponse)
def corroborate_all(db: Session = Depends(get_db)) -> CorroborationResponse:
    """Corrobore TOUTES les alertes en une passe (un seul appel reseau,
    ~23 s pour 1183 annonces indexees en memoire)."""
    outcome = corroborate_corpus(db)
    return CorroborationResponse(
        success=outcome.success,
        feed_size=outcome.feed_size,
        detections_checked=outcome.detections_checked,
        detections_corroborated=outcome.detections_corroborated,
        alerts_corroborated=outcome.alerts_corroborated,
        error=outcome.error,
    )


@router.post("/{alert_id}/summarize", response_model=AlertOut)
async def summarize(alert_id: uuid.UUID, db: Session = Depends(get_db)) -> AlertOut:
    """Genere (via LLM, modele actuellement selectionne dans /api/llm/select)
    et persiste le resume de l'alerte -- a la demande, jamais automatique
    (voir pipeline/alerting/summarize.py). Ecrase un resume precedent s'il y
    en avait un."""
    alert_repo = AlertRepository(db)
    alert = alert_repo.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Une alerte regionale n'a pas d'entite (migration 0016) : le resume porte
    # alors sur le perimetre geographique. Renvoyer « Entity not found »
    # laisserait croire a une donnee manquante.
    entity = EntityRepository(db).get(alert.entity_id) if alert.entity_id else None
    if entity is None and alert.entity_id is not None:
        raise HTTPException(status_code=404, detail="Entity not found")

    try:
        alert.summary = await summarize_alert(
            alert,
            sujet_alerte(db, alert),
            get_selected_model(),
            victim_claims(db, alert),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Echec de l'appel au modele: {exc}"
        ) from exc

    alert = alert_repo.update(alert)
    return _sortie(db, [alert])[0]


@router.get("/{alert_id}/report.pdf")
async def rapport_pdf(
    alert_id: uuid.UUID,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
):
    """Rapport d'incident en PDF, redige par le LLM, pret a etre transmis.

    ⚠️ Ce document SORT de l'outil : il ne contient que des valeurs masquees,
    des metadonnees et des liens de preuve -- jamais de valeur brute ni de
    contenu de fuite (regle 2).

    ⚠️ Un LLM indisponible ne fait PAS echouer le rapport : les faits, sources
    et preuves sont produits par le code, la synthese est un confort de
    lecture. Le document le dit alors explicitement.
    """
    alert = _alerte(db, alert_id)
    # ⚠️ L'ACCES LE PLUS SENSIBLE A TRACER : ce document SORT de l'outil et
    # circule ensuite hors de tout controle. Journalise AVANT la generation --
    # si le LLM ou fpdf echoue, la demande a quand meme eu lieu.
    journaliser_acces(db, utilisateur, "report", alert_id=alert_id)
    pdf, nom = await generer_rapport_pdf(db, alert, get_selected_model())
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.get("/{alert_id}/stix.json")
def export_stix(
    alert_id: uuid.UUID,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
):
    """Alerte au format STIX 2.1 -- le format d'echange d'un CERT.

    ⚠️ Comme le rapport PDF, ce paquet SORT de l'outil : journalise AVANT sa
    production (regle 5). Il ne contient que du public et du citable -- jamais
    une valeur detectee, meme masquee, ni un `.onion` (regles 1 et 2) -- et
    porte TLP:AMBER+STRICT sur chaque objet."""
    alert = _alerte(db, alert_id)
    journaliser_acces(db, utilisateur, "export", alert_id=alert_id)
    paquet, nom = exporter_stix(db, alert)
    return Response(
        content=json.dumps(paquet, ensure_ascii=False, indent=2),
        media_type="application/stix+json;version=2.1",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.post("/{alert_id}/remind", response_model=AlertOut)
def remind_alert(alert_id: uuid.UUID, db: Session = Depends(get_db)) -> AlertOut:
    """Redemande l'attention sur une alerte deja existante.

    ⚠️ NE CREE PAS d'alerte. Depuis le dedoublonnage par victime, une
    organisation deja signalee ne redeclenche plus rien, meme redetectee par
    une autre source -- c'est voulu : `transports-exemple.com`, publiee par
    KRYBIT ET par NIGHT SPIRE, est un seul incident. Le rappel est la maniere
    ASSUMEE de se faire re-solliciter dessus.

    Creer une seconde alerte reintroduirait exactement le doublon que le
    dedoublonnage supprime : le rappel serait une regression deguisee en
    fonctionnalite. Il marque donc l'alerte et la remet en `open`, de sorte
    qu'elle remonte dans le tri sans polluer le decompte.
    """
    repo = AlertRepository(db)
    alert = repo.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.reminded_at = datetime.now(timezone.utc)
    alert.reminder_count = (alert.reminder_count or 0) + 1
    # Une alerte classee que l'analyste veut revoir doit redevenir actionnable.
    alert.status = "open"
    # La qualification de cloture (traitee, faux positif...) ne vaut plus pour
    # une alerte rouverte : la garder ferait compter un faux positif rouvert
    # dans les statistiques de la Gouvernance.
    alert.resolution_reason = None
    return _sortie(db, [repo.update(alert)])[0]


class DigestResponse(BaseModel):
    model_config = {"extra": "forbid"}

    alert_count: int
    model: str
    digest: str
    # Perimetre reellement resume, en clair. Affiche a cote du texte : sans
    # lui, « 3 alertes » a cote d'une liste de 120 est incomprehensible.
    scope: str


# Plafond de chargement. La synthese porte sur les alertes OUVERTES : une
# alerte classee a deja ete traitee et n'a pas sa place dans « ce qu'il reste
# a faire ».
_MAX_ALERTS_FOR_DIGEST = 200


_ORDRE_SEVERITE = ("critical", "high", "medium", "low")


def _libelle_scope(
    severites: list[str] | None,
    alert_date: date | None,
    status: AlertStatus | None,
    groupe: str | None = None,
) -> str:
    """Perimetre reellement resume, en francais.

    ⚠️ Enonce ce qui a ete RETENU, pas ce qui a ete demande : quand aucun
    filtre n'est pose, dire « toutes » est la seule formulation qui ne laisse
    pas croire a un cadrage.
    """
    morceaux = []
    if groupe:
        morceaux.append(f"groupe {groupe} et ses filiales")
    if severites:
        ordonnees = [s for s in _ORDRE_SEVERITE if s in severites]
        morceaux.append("sévérité " + ", ".join(ordonnees))
    else:
        morceaux.append("toutes severites")
    morceaux.append(
        f"journée du {alert_date.isoformat()}" if alert_date else "toutes dates"
    )
    morceaux.append(f"statut {status.value}" if status is not None else "tous statuts")
    return " · ".join(morceaux)


@router.post("/digest", response_model=DigestResponse)
async def digest_alerts(
    db: Session = Depends(get_db),
    severity: Annotated[list[AlertSeverity] | None, Query()] = None,
    alert_date: date | None = None,
    status: AlertStatus | None = AlertStatus.OPEN,
    group_id: uuid.UUID | None = None,
) -> DigestResponse:
    """Synthese LLM de l'ENSEMBLE des alertes, en un seul texte.

    Complementaire de `/{id}/summarize`, qui resume une alerte : ici on repond
    a « qu'est-ce qui s'est passe, globalement ? » -- la vue qu'un analyste
    regarde en arrivant.

    Cadrable par SEVERITE et par JOURNEE (`alert_date`) : « ce qui est arrive
    aujourd'hui » et « ce qui est grave » sont deux questions distinctes, et
    une synthese qui melange 120 alertes de tous niveaux et de toutes dates ne
    repond ni a l'une ni a l'autre.

    Le contenu envoye au LLM est borne (voir alerting/digest.py) et le surplus
    eventuel est ANNONCE dans le texte plutot que coupe en silence : un resume
    qui tait ce qu'il ignore est pire qu'un resume incomplet.

    ⚠️ Le perimetre retenu est RENVOYE (`scope`) et doit etre affiche a cote du
    texte : un resume dont on ignore l'assiette n'est pas verifiable -- meme
    raison que le perimetre affiche par le test de disponibilite des sources.
    """
    repo = AlertRepository(db)
    severites = [s.value for s in severity] if severity else None
    alerts = repo.list(
        limit=_MAX_ALERTS_FOR_DIGEST,
        status=status.value if status is not None else None,
        severities=severites,
        alert_date=alert_date,
        group_id=group_id,
    )

    entity_repo = EntityRepository(db)
    groupe = entity_repo.get(group_id) if group_id is not None else None
    noms: dict = {}
    for alert in alerts:
        if alert.entity_id is not None and alert.entity_id not in noms:
            entity = entity_repo.get(alert.entity_id)
            if entity is not None:
                noms[alert.entity_id] = entity.name

    model = get_selected_model()
    scope = _libelle_scope(
        severites, alert_date, status, groupe.name if groupe else None
    )

    # ⚠️ Aucune alerte : on NE SOLLICITE PAS le modele. Mesure du 2026-09-04 --
    # sur un perimetre vide il a rendu 600 caracteres de vide poli (« Aucune
    # priorite ne peut etre etablie car... ») en 66 secondes. Un fait tient en
    # une ligne, et le faire ecrire par un modele n'ajoute que du delai et un
    # risque de formulation.
    if not alerts:
        return DigestResponse(
            alert_count=0,
            model=model,
            digest=f"Aucune alerte sur ce perimetre ({scope}).",
            scope=scope,
        )

    content = build_digest_content(alerts, noms)
    try:
        texte = await generate_response(
            model, content, DIGEST_QUERY, temperature=settings.SUMMARY_LLM_TEMPERATURE
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DigestResponse(
        alert_count=len(alerts),
        model=model,
        digest=texte,
        scope=scope,
    )


class AlertDetectionOut(BaseModel):
    model_config = {"extra": "forbid"}

    id: uuid.UUID
    type: str
    value_masked: str
    severity: str | None
    validated: bool
    corroborated_group: str | None
    corroboration_status: str | None = None
    corroborated_groups: list[str] | None = None
    corroboration_match: str | None = None


class AlertEvidenceDocument(BaseModel):
    model_config = {"extra": "forbid"}

    document_id: uuid.UUID
    title: str | None
    # URL d'origine : souvent un `.onion`, donc consultable seulement via Tor.
    # C'est ce que NOUS avons lu, a distinguer de la preuve clearnet portee par
    # l'alerte (`corroboration_evidence_url`).
    url: str
    source_name: str | None
    collector: str
    published_at: datetime | None
    fetched_at: datetime
    content_preview: str
    detections: list[AlertDetectionOut]


class AlertEvidenceResponse(BaseModel):
    model_config = {"extra": "forbid"}

    alert_id: uuid.UUID
    document_count: int
    documents: list[AlertEvidenceDocument]


# Plafond d'affichage. L'alerte Organisation Exemple porte 144 detections reparties sur
# quelques documents ; une alerte pathologique ne doit pas rendre la page
# inutilisable.
_MAX_EVIDENCE_DOCUMENTS = 100


@router.get("/{alert_id}/documents", response_model=AlertEvidenceResponse)
def alert_documents(alert_id: uuid.UUID, db: Session = Depends(get_db)):
    """Documents SOURCES d'une alerte, avec les detections qu'ils ont produites.

    Sans cette route, la page Alertes affichait « 144 detection(s) » et
    l'analyste n'avait aucun chemin vers la preuve : une alerte qu'on ne peut
    pas verifier n'est qu'une affirmation. C'est ici qu'il remonte au document
    d'origine pour contre-verifier.

    Ne transporte que des valeurs deja masquees (regle 2) : `value_masked` et
    l'apercu de contenu, jamais la valeur brute d'une detection.
    """
    alert = AlertRepository(db).get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    detections = [ad.detection for ad in alert.detections if ad.detection]
    par_document: dict[uuid.UUID, list] = {}
    for detection in detections:
        par_document.setdefault(detection.document_id, []).append(detection)

    document_repo = RawDocumentRepository(db)
    documents = document_repo.list_by_ids(
        list(par_document), limit=_MAX_EVIDENCE_DOCUMENTS
    )

    source_repo = SourceRepository(db)
    noms_sources: dict[uuid.UUID, str] = {}
    sorties = []
    for document in documents:
        if document.source_id not in noms_sources:
            source = source_repo.get(document.source_id)
            noms_sources[document.source_id] = source.name if source else None
        sorties.append(
            AlertEvidenceDocument(
                document_id=document.id,
                title=document.title,
                url=document.url,
                source_name=noms_sources[document.source_id],
                collector=document.collector,
                published_at=document.published_at,
                fetched_at=document.fetched_at,
                content_preview=(document.content or "")[:280],
                detections=[
                    AlertDetectionOut(
                        id=d.id,
                        type=d.type,
                        value_masked=d.value_masked,
                        severity=d.severity,
                        validated=d.validated,
                        corroborated_group=d.corroborated_group,
                        corroboration_status=d.corroboration_status,
                        corroborated_groups=d.corroborated_groups,
                        corroboration_match=d.corroboration_match,
                    )
                    for d in par_document.get(document.id, [])
                ],
            )
        )

    return AlertEvidenceResponse(
        alert_id=alert.id,
        # Le compte porte sur les documents REELS de l'alerte, pas sur la page
        # renvoyee : si le plafond tronque, l'ecart doit rester visible.
        document_count=len(par_document),
        documents=sorties,
    )


# --------------------------------------------------------------------------
# Mode operatoire des gangs (TTP MITRE, outils, CVE) -- voir
# services/gang_profile_service.py
# --------------------------------------------------------------------------


class GangTechniqueOut(BaseModel):
    model_config = {"extra": "forbid"}

    tactic_id: str
    tactic_name: str
    technique_id: str
    technique_name: str
    details: str | None
    url: str | None


class GangCveOut(BaseModel):
    model_config = {"extra": "forbid"}

    cve: str
    url: str | None


class GangToolGroupOut(BaseModel):
    model_config = {"extra": "forbid"}

    # Categorie publiee par la source (`Exfiltration`, `RMM-Tools`...) ; ""
    # si elle n'en donne pas.
    category: str
    tools: list[str]


class GangModusOperandiOut(BaseModel):
    model_config = {"extra": "forbid"}

    gang: str
    # documented | undocumented | unavailable -- `unavailable` est une absence
    # de MESURE, jamais « aucun mode operatoire connu ».
    status: str
    victims: list[str]
    techniques: list[GangTechniqueOut]
    tool_groups: list[GangToolGroupOut]
    cves: list[GangCveOut]


class AlertModusOperandiResponse(BaseModel):
    model_config = {"extra": "forbid"}

    alert_id: uuid.UUID
    caveat: str
    gangs: list[GangModusOperandiOut]


@router.get("/{alert_id}/modus-operandi", response_model=AlertModusOperandiResponse)
def alert_modus_operandi(alert_id: uuid.UUID, db: Session = Depends(get_db)):
    """Mode operatoire de chaque gang revendiquant une victime de l'alerte.

    Appel tiers a la demande (cache 7 jours). Un tiers injoignable rend le
    gang `unavailable` ; la route ne leve pas pour autant."""
    alert = AlertRepository(db).get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    gangs = []
    for mo in modus_operandi(db, alert):
        profil = mo.profile
        gangs.append(
            GangModusOperandiOut(
                gang=mo.gang,
                status=mo.status.value,
                victims=list(mo.victims),
                techniques=[
                    GangTechniqueOut(
                        tactic_id=t.tactic_id,
                        tactic_name=t.tactic_name,
                        technique_id=t.technique_id,
                        technique_name=t.technique_name,
                        details=t.details,
                        url=mitre_technique_url(t.technique_id),
                    )
                    for t in (profil.techniques if profil else ())
                ],
                tool_groups=[
                    GangToolGroupOut(category=categorie, tools=list(noms))
                    for categorie, noms in (profil.tool_groups if profil else ())
                ],
                cves=[
                    GangCveOut(cve=c, url=cve_url(c))
                    for c in (profil.cves if profil else ())
                ],
            )
        )
    return AlertModusOperandiResponse(
        alert_id=alert.id, caveat=MODUS_OPERANDI_CAVEAT, gangs=gangs
    )
