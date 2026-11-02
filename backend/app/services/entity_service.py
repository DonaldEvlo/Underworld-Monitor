"""Groupe, filiales, pays et secteur déclarés d'une organisation surveillée
(migration 0033, 2026-10-05).

Le service porte les CONTRÔLES (un seul niveau de hiérarchie, pays ISO,
secteur connu) et les CONSÉQUENCES d'une modification : les alertes de
l'organisation reprennent aussitôt le pays et le secteur déclarés, et leur
gravité est recalculée -- sinon la page afficherait l'ancienne valeur
jusqu'à la passe horaire suivante.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.alert import Alert
from app.db.models.entity import Entity
from app.pipeline.reporting.governance import SECTEURS_FR

_PAYS = re.compile(r"^[A-Z]{2}$")
# Vocabulaire `activity` de ransomware.live, sans les sentinelles de
# regroupement : c'est lui que lit la gravité NIS2 (rules.CRITICAL_SECTORS).
SECTEURS_DECLARABLES = frozenset(
    k for k in SECTEURS_FR if k not in ("non renseigne", "autres")
)


class EntityError(ValueError):
    """Déclaration refusée ; le message est affiché tel quel à l'analyste."""


def normaliser_pays(pays: str | None) -> str | None:
    if pays is None or not pays.strip():
        return None
    code = pays.strip().upper()
    if not _PAYS.match(code):
        raise EntityError(
            "Le pays attendu est un code ISO à deux lettres (ex. SN, CI, ML)."
        )
    return code


def normaliser_secteur(secteur: str | None) -> str | None:
    if secteur is None or not secteur.strip():
        return None
    if secteur not in SECTEURS_DECLARABLES:
        raise EntityError(f"Secteur inconnu : {secteur}.")
    return secteur


def controler_parent(
    db: Session, entite_id: uuid.UUID | None, parent_id: uuid.UUID | None
) -> None:
    """UN niveau seulement (décision D1) : un groupe n'a pas de groupe parent,
    et une organisation qui a des filiales ne peut pas devenir filiale."""
    if parent_id is None:
        return
    if entite_id is not None and parent_id == entite_id:
        raise EntityError("Une organisation ne peut pas être son propre groupe.")
    parent = db.get(Entity, parent_id)
    if parent is None:
        raise EntityError("Groupe parent introuvable.")
    if parent.parent_id is not None:
        raise EntityError(
            f"« {parent.name} » est déjà une filiale : un seul niveau de groupe est permis."
        )
    if entite_id is not None:
        a_des_filiales = db.execute(
            select(Entity.id).where(Entity.parent_id == entite_id).limit(1)
        ).first()
        if a_des_filiales:
            raise EntityError(
                "Cette organisation a des filiales : elle ne peut pas devenir elle-même filiale."
            )


def reporter_sur_les_alertes(db: Session, entite_id: uuid.UUID) -> None:
    """Après une modification de pays ou de secteur : les alertes de
    l'organisation prennent la nouvelle valeur et leur gravité est
    recalculée, bornée à ces alertes (piège de portée du 2026-09-15)."""
    from app.services.alert_service import refresh_alert_severities
    from app.services.victim_intel_service import apply_effective_facts

    ids = [
        a for (a,) in db.execute(select(Alert.id).where(Alert.entity_id == entite_id))
    ]
    if not ids:
        return
    apply_effective_facts(db, alert_ids=ids)
    refresh_alert_severities(db, apply=True, alert_ids=ids)
