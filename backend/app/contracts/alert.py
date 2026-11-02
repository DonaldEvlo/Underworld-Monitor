from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class AlertSeverity(str, Enum):
    """Niveau de criticite, derive de regles explicites sur validated/
    is_relevant/type (voir pipeline/alerting/rules.py --
    proposition a valider, pas figee, voir CONTRIBUTING.md §9.3)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    """Cycle de vie cote analyste, independant de la severite."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AlertContract(BaseModel):
    """Une alerte adressee a une entite surveillee (voir contracts/entity.py),
    regroupant une ou plusieurs detections liees (voir
    contracts/alert_detection.py) -- une alerte par incident, pas une par
    detection individuelle, pour eviter de noyer l'analyste (voir CONTRIBUTING.md
    §8 : sur 5503 detections, seules 453 sont a la fois validees et
    pertinentes).

    C'est le livrable produit final (voir CONTRIBUTING.md §1) : jamais de donnee
    brute ici, uniquement des references vers des DetectionContract deja
    masques."""

    model_config = {"extra": "forbid"}

    id: UUID
    entity_id: UUID
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.OPEN

    # Resume LLM en bout de pipeline, batch, jamais dans le chemin critique
    # d'ingestion (voir CONTRIBUTING.md §3.4 et pipeline/alerting/summarize.py --
    # pas encore ecrit, champ present des maintenant pour ne pas revenir sur
    # ce contrat plus tard). Absent tant que summarize.py n'a pas tourne.
    summary: str | None = None

    created_at: datetime
