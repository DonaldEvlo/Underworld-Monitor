from __future__ import annotations

import builtins

import uuid

from sqlalchemy.orm import Session, joinedload

from app.contracts.entity import (
    EntityContract,
    SelectorType,
    VerificationMethod,
    VerificationStatus,
)
from app.contracts.entity import EntitySelector as EntitySelectorContract
from app.db.models.entity import Entity, EntitySelector


def to_entity_contract(entity: Entity) -> EntityContract:
    """Modèle -> contrat. SEULE conversion du projet : elle était recopiée à
    quatre endroits (routeurs entities et stats, services d'alerte et de
    sévérité), si bien qu'ajouter un champ au contrat (groupe, pays, secteur,
    2026-10-05) aurait exigé quatre modifications identiques."""
    return EntityContract(
        id=entity.id,
        name=entity.name,
        active=entity.active,
        selectors=[
            EntitySelectorContract(type=SelectorType(s.type), value=s.value)
            for s in entity.selectors
        ],
        verification_method=(
            VerificationMethod(entity.verification_method)
            if entity.verification_method
            else None
        ),
        verification_status=VerificationStatus(entity.verification_status),
        verified_at=entity.verified_at,
        parent_id=entity.parent_id,
        country=entity.country,
        sector=entity.sector,
        created_at=entity.created_at,
    )


class EntityRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, id: uuid.UUID) -> Entity | None:
        return (
            self.db.query(Entity)
            .options(joinedload(Entity.selectors))
            .filter(Entity.id == id)
            .first()
        )

    def list(self) -> builtins.list[Entity]:
        return list(
            self.db.query(Entity)
            .options(joinedload(Entity.selectors))
            .order_by(Entity.created_at.desc())
            .all()
        )

    def list_active(self) -> builtins.list[Entity]:
        return list(
            self.db.query(Entity)
            .options(joinedload(Entity.selectors))
            .filter(Entity.active.is_(True))
            .all()
        )

    def create(self, entity: Entity) -> Entity:
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def update(self, entity: Entity) -> Entity:
        """Persiste les modifications faites sur une instance deja attachee a
        la session (attributs assignes par l'appelant avant l'appel) -- meme
        patron que KeywordRepository.update."""
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def replace_selectors(
        self, entity: Entity, selectors: builtins.list[EntitySelector]
    ) -> Entity:
        """Remplace entierement les selecteurs d'une entite -- plus simple et
        moins sujet aux incoherences qu'un diff partiel pour une liste courte
        (une entite a rarement plus de quelques selecteurs)."""
        entity.selectors.clear()
        entity.selectors.extend(selectors)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def by_ids_with_parents(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, Entity]:
        """Les entites demandees ET leurs groupes parents, en deux requetes :
        de quoi afficher « filiale · groupe » sur une page d'alertes."""
        if not ids:
            return {}
        trouvees = {
            e.id: e for e in self.db.query(Entity).filter(Entity.id.in_(ids)).all()
        }
        parents = {e.parent_id for e in trouvees.values() if e.parent_id} - set(
            trouvees
        )
        if parents:
            for e in self.db.query(Entity).filter(Entity.id.in_(parents)).all():
                trouvees[e.id] = e
        return trouvees

    def names_by_id(self) -> dict[uuid.UUID, str]:
        """Nom de chaque entite, pour libeller des alertes sans jointure."""
        return {e.id: e.name for e in self.db.query(Entity).all()}

    def delete(self, id: uuid.UUID) -> None:
        entity = self.db.get(Entity, id)
        if entity is not None:
            self.db.delete(entity)
            self.db.commit()
