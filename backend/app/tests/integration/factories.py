"""Fabriques de donnees pour les tests d'integration.

Aucun nettoyage a ecrire : chaque test tourne dans une transaction annulee
(conftest.py). Les noms et valeurs sont uniques pour ne jamais se confondre
avec les donnees reelles de la base de developpement, que ces tests lisent.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.db.models.alert import Alert, AlertDetection
from app.db.models.detection import Detection
from app.db.models.entity import Entity, EntitySelector
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source


def unique(prefixe: str = "t") -> str:
    return f"{prefixe}{uuid.uuid4().hex[:10]}"


def source(db, *, name: str | None = None, type_: str = "onion") -> Source:
    ligne = Source(
        id=uuid.uuid4(),
        name=name or f"{unique('TESTGANG')} (DLS)",
        type=type_,
        url=f"http://{unique()}.onion",
        active=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ligne)
    db.flush()
    return ligne


def document(
    db,
    src: Source,
    *,
    collector: str = "dls",
    title: str | None = None,
    url: str | None = None,
    content: str = "Victime annoncee",
    source_meta: dict | None = None,
    fetched_at: datetime | None = None,
) -> RawDocument:
    ligne = RawDocument(
        id=uuid.uuid4(),
        source_id=src.id,
        url=url or f"{src.url}/post/{unique()}",
        title=title,
        content=content,
        content_hash=uuid.uuid4().hex,
        fetched_at=fetched_at or datetime.now(timezone.utc),
        source_type=src.type,
        collector=collector,
        collector_version="test",
        is_duplicate=False,
        source_meta=source_meta,
    )
    db.add(ligne)
    db.flush()
    return ligne


def detection(
    db,
    doc: RawDocument,
    *,
    type_: str = "domain",
    value_masked: str | None = None,
    is_relevant: bool = True,
    validated: bool = False,
) -> Detection:
    ligne = Detection(
        id=uuid.uuid4(),
        document_id=doc.id,
        type=type_,
        value_masked=value_masked or f"{unique('victime')}.co.za",
        value_hash=uuid.uuid4().hex,
        validated=validated,
        is_relevant=is_relevant,
        created_at=datetime.now(timezone.utc),
    )
    db.add(ligne)
    db.flush()
    return ligne


def entity(db, *, domain: str) -> Entity:
    ligne = Entity(id=uuid.uuid4(), name=unique("Entite "), active=True)
    db.add(ligne)
    db.flush()
    db.add(
        EntitySelector(id=uuid.uuid4(), entity_id=ligne.id, type="domain", value=domain)
    )
    db.flush()
    return ligne


def alert(
    db, detections: list[Detection], *, ent: Entity | None = None, **champs
) -> Alert:
    ligne = Alert(
        id=uuid.uuid4(),
        entity_id=ent.id if ent else None,
        scope="entity" if ent else "region",
        region=champs.pop("region", None if ent else "Afrique"),
        severity=champs.pop("severity", "medium"),
        status="open",
        alert_date=date.today(),
        created_at=datetime.now(timezone.utc),
        **champs,
    )
    db.add(ligne)
    db.flush()
    for d in detections:
        db.add(AlertDetection(id=uuid.uuid4(), alert_id=ligne.id, detection_id=d.id))
    db.commit()
    db.refresh(ligne)
    return ligne


def victime_alertee(db, *, source_name: str | None = None, **meta):
    """Raccourci : source DLS -> document -> detection de domaine -> entite
    surveillee -> alerte. Rend (source, document, detection, alerte)."""
    src = source(db, name=source_name)
    domaine = f"{unique('victime')}.co.za"
    doc = document(
        db,
        src,
        title=domaine,
        source_meta={
            "victim_name": domaine,
            "victim_site": f"http://{domaine}",
            **meta,
        },
    )
    det = detection(db, doc, value_masked=domaine)
    ent = entity(db, domain=domaine)
    return src, doc, det, alert(db, [det], ent=ent)
