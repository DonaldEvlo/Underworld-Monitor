import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.detection import Detection


class Alert(Base):
    """Une alerte adressee a une entite surveillee, regroupant les detections
    du jour qui depassent le seuil de severite (voir pipeline/alerting/rules.py
    et services/alert_service.py). Voir contracts/alert.py pour le contrat
    Pydantic correspondant.

    Une seule alerte par (entity_id, alert_date) -- contrainte unique en base,
    voir migration 0011 -- pour rester idempotent si le service d'orchestration
    est relance plusieurs fois le meme jour (pas de worker planifie, tout
    tourne a la demande, voir CONTRIBUTING.md)."""

    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # NULLABLE depuis la migration 0016 : une alerte peut porter sur une REGION
    # plutot que sur une entite declaree (voir `scope`). Toujours renseigne
    # quand `scope == "entity"`.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, index=True
    )
    # "entity" (comportement historique) ou "region".
    #
    # L'alerte regionale repond au goulot mesure le 2026-09-02 : la collecte
    # trouvait 3101 domaines de victimes pour 31 surveilles, soit 1 % de
    # conversion. Une victime situee dans un perimetre geographique surveille
    # alerte desormais meme si personne ne l'a declaree.
    scope: Mapped[str] = mapped_column(String, nullable=False, default="entity")
    # Continent surveille, pour une alerte regionale. NULL pour une alerte
    # d'entite -- c'est ce qui rend l'index d'unicite partiel efficace.
    region: Mapped[str | None] = mapped_column(String)
    # Victime normalisee d'une alerte REGIONALE (migration 0032) : une alerte
    # par victime, pour que gravite, credibilite et date d'attaque soient
    # calculees sur UNE organisation et non sur un agregat. NULL pour une
    # alerte d'entite, et pour les alertes regionales anterieures non scindees.
    victim_key: Mapped[str | None] = mapped_column(String)
    # Rappel demande par un analyste (migration 0017). Une organisation deja
    # signalee ne redeclenche plus d'alerte meme redetectee ailleurs ; le
    # rappel est la facon ASSUMEE de se faire re-solliciter.
    #
    # ⚠️ Un rappel ne cree pas d'alerte : il marque celle-ci et la remet en
    # `open`. En creer une seconde reintroduirait le doublon que le
    # dedoublonnage par victime vient de supprimer.
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    alert_date: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)

    # Agregat de corroboration au niveau du livrable (voir
    # pipeline/enrich/ransomlook_corroboration.py). `corroborated_count`
    # compte les detections de CETTE alerte confirmees par un second
    # observateur -- 0 avec un statut `exclusive` signifie « nous seuls
    # voyons cette victime », ce qui n'est pas un defaut de fiabilite : nous
    # lisons le DLS a la source, l'agregateur ne l'a peut-etre pas encore
    # indexe.
    corroboration_status: Mapped[str | None] = mapped_column(String)
    corroborated_group: Mapped[str | None] = mapped_column(String)
    corroborated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    corroborated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Preuve consultable par un tiers (voir detection.py).
    corroboration_evidence_url: Mapped[str | None] = mapped_column(String)
    # Migration 0024 : tous les gangs qui revendiquent les victimes de
    # l'alerte, et la date d'indexation la plus ancienne chez RansomLook.
    corroborated_groups: Mapped[list | None] = mapped_column(JSONB)
    corroboration_first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Migration 0025 : observateurs tiers ayant vu les victimes de l'alerte
    # (`ransomlook`, `ransomware_live`), union sur les detections confirmees.
    corroboration_observers: Mapped[list | None] = mapped_column(JSONB)

    # --- Renseignements par victime (migration 0026) -------------------
    # ⚠️ AUCUNE PII : que des COMPTEURS, des DATES et des LIBELLES. Verrouille
    # par `test_victim_intel.TestAucunePII`, qui contraint la FORME du contrat
    # source. Meme doctrine que `known_breached` (HIBP) : on enregistre
    # COMBIEN et DEPUIS QUAND, jamais QUI ni QUOI.
    #
    # ⚠️ TOUS CES CHAMPS NE VEULENT RIEN DIRE TANT QUE `intel_refreshed_at`
    # EST NULL. `compromised_users = 0` se lit « mesure, et nul » ; NULL se
    # lit « jamais mesure ». Ne jamais confondre les deux dans un calcul de
    # severite -- meme convention que `corroboration_status` NULL.
    victim_attack_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    victim_sector: Mapped[str | None] = mapped_column(String)
    victim_country: Mapped[str | None] = mapped_column(String)
    # `employees` = personnel, `users` = clients, `thirdparties` =
    # prestataires. Distinction posee sur le ROLE vis-a-vis de l'organisation,
    # JAMAIS sur la personne (precedent DOXBYTE).
    compromised_employees: Mapped[int | None] = mapped_column(Integer)
    compromised_users: Mapped[int | None] = mapped_column(Integer)
    compromised_thirdparties: Mapped[int | None] = mapped_column(Integer)
    stealer_families: Mapped[list | None] = mapped_column(JSONB)
    last_employee_compromised: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_user_compromised: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    intel_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Confirmation par la presse (migration 0030) -------------------
    # Signal de CREDIBILITE (« la fuite est-elle reelle ? »), distinct de la
    # corroboration (« notre lecture est-elle juste ? »). NULL = aucune
    # confirmation connue, JAMAIS « fuite fausse » : la presse couvre surtout
    # les grandes organisations, et avec retard.
    press_source_url: Mapped[str | None] = mapped_column(String)
    press_evidence_url: Mapped[str | None] = mapped_column(String)
    press_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Credibilite (migration 0031) -----------------------------------
    # « La fuite est-elle reelle ? », axe DISTINCT de la gravite. Voir
    # pipeline/alerting/credibility.py. NULL = jamais evalue ;
    # `not_evaluated` = evalue, sans document source.
    credibility_level: Mapped[str | None] = mapped_column(String, index=True)
    credibility_evidence: Mapped[str | None] = mapped_column(String)
    credibility_assessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # --- Travail d'analyste -------------------------------------------
    # ⚠️ Sans ces champs, deux analystes ne peuvent pas se repartir les
    # alertes, et « faux positif ecarte » est indistinguable de « incident
    # reel traite » -- donc l'historique des faux positifs, seule matiere
    # permettant d'ajuster les seuils plus tard, est perdu.
    assignee: Mapped[str | None] = mapped_column(String)
    analyst_note: Mapped[str | None] = mapped_column(Text)
    # `confirmed` | `false_positive` | `duplicate` | `out_of_scope`
    resolution_reason: Mapped[str | None] = mapped_column(String)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Migration 0033 -- corrections d'analyste. `severity`, `victim_country`
    # et `victim_sector` portent la valeur EFFECTIVE (lue partout) ;
    # `computed_*` ce que la plateforme a calculé ; `*_override` la décision
    # de l'analyste. ⚠️ Les passes automatiques n'écrivent que `computed_*`
    # quand une correction existe : sinon elles l'effaceraient dans l'heure
    # (constaté sur l'exposition d'identifiants le 2026-10-01).
    computed_severity: Mapped[str | None] = mapped_column(String)
    computed_country: Mapped[str | None] = mapped_column(String)
    computed_sector: Mapped[str | None] = mapped_column(String)
    severity_override: Mapped[str | None] = mapped_column(String)
    country_override: Mapped[str | None] = mapped_column(String)
    sector_override: Mapped[str | None] = mapped_column(String)
    override_reason: Mapped[str | None] = mapped_column(Text)
    override_by: Mapped[str | None] = mapped_column(String)
    override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    detections: Mapped[list["AlertDetection"]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )


class AlertDetection(Base):
    """Table de jonction entre une Alert et les Detection qui l'ont declenchee
    (voir contracts/alert_detection.py). Une detection ne rattache qu'une
    seule fois a une meme alerte -- contrainte unique en base, voir migration
    0011."""

    __tablename__ = "alert_detections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id"), nullable=False, index=True
    )
    detection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("detections.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    alert: Mapped[Alert] = relationship(back_populates="detections")
    # Lecture seule cote Detection (pas de back_populates) : Detection n'a pas
    # besoin de connaitre ses alertes pour son propre usage (listing/filtrage
    # dans api/routers/detections.py), seul ce sens (alerte -> detection) sert
    # a summarize.py.
    detection: Mapped["Detection"] = relationship(viewonly=True)
