"""Le périmètre surveillé, vu par le RSSI (2026-10-05).

Ouvert à TOUS les rôles : le RSSI (`viewer`) en est le destinataire premier,
l'analyste et l'administrateur y ont la même vue de pilotage. Les réponses ne
contiennent que des faits de SYNTHÈSE (voir pipeline/reporting/perimeter) :
ni détection, ni preuve, ni victime hors périmètre.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import exige_role, get_current_user, get_db
from app.core.roles import TOUS
from app.db.models.user import User
from app.services.alert_access_service import journaliser_acces
from app.services.perimeter_service import alertes_de, perimetre

router = APIRouter(
    prefix="/api/perimeter",
    tags=["perimeter"],
    dependencies=[Depends(exige_role(TOUS))],
)


@router.get("")
def vue_perimetre(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Arbre groupes -> filiales, état et alertes ouvertes de chacune."""
    return perimetre(db)


@router.get("/{entity_id}/alerts")
def alertes_organisation(
    entity_id: uuid.UUID,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Synthèse des alertes d'une organisation (et de ses filiales).

    ⚠️ Journalisée comme une consultation d'alertes (règle 5) : même au niveau
    de synthèse, la liste nomme des organisations touchées."""
    resultat = alertes_de(db, entity_id)
    if resultat is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    journaliser_acces(db, utilisateur, "list")
    return resultat
