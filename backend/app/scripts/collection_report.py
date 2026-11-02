"""Garde-fou de verification post-collecte.

Contexte : un test de collecteur qui appelle `Collector.collect()` directement
dans un script Python peut "reussir" (aucune exception, documents produits en
memoire) sans jamais avoir persiste quoi que ce soit -- c'est exactement ce
qui est arrive pour Akira/DARKNET ARMY/BreachForums, verifie uniquement en
memoire, jamais passe par `POST /api/sources/{id}/collect` qui ecrit en base.

Ce script ne fait aucune hypothese sur "le code a tourne sans erreur" : il
interroge `raw_documents` directement et signale les sources qui n'ont RIEN
en base malgre un `last_collected_at` renseigne (signe qu'une collecte a ete
declenchee mais n'a produit aucune ligne persistee) ou qui n'ont jamais ete
collectees du tout.

Usage :
    docker compose exec backend python -m app.scripts.collection_report
    docker compose exec backend python -m app.scripts.collection_report --active-only
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import func

from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.db.session import SessionLocal


def build_report(active_only: bool) -> tuple[list[dict], list[str]]:
    """Retourne (lignes du rapport, avertissements)."""
    with SessionLocal() as db:
        counts = dict(
            db.query(RawDocument.source_id, func.count(RawDocument.id))
            .group_by(RawDocument.source_id)
            .all()
        )
        latest = dict(
            db.query(RawDocument.source_id, func.max(RawDocument.fetched_at))
            .group_by(RawDocument.source_id)
            .all()
        )

        query = db.query(Source)
        if active_only:
            query = query.filter(Source.active.is_(True))
        sources = query.order_by(Source.name).all()

    rows = []
    warnings = []
    for source in sources:
        doc_count = counts.get(source.id, 0)
        last_doc_at = latest.get(source.id)
        rows.append(
            {
                "name": source.name,
                "active": source.active,
                "last_collected_at": source.last_collected_at,
                "document_count": doc_count,
                "last_document_at": last_doc_at,
            }
        )

        # Le signal precis du bug qu'on a rencontre : la source a bien ete
        # "collectee" (last_collected_at renseigne) mais 0 document en base --
        # ca ne peut arriver que si la collecte n'a jamais persiste, pas si
        # elle a simplement echoue (dans ce cas last_collected_at n'est pas mis
        # a jour, voir _collect_source dans sources.py).
        if source.last_collected_at is not None and doc_count == 0:
            warnings.append(
                f"⚠ {source.name}: last_collected_at renseigne ({source.last_collected_at}) "
                f"mais 0 document en base -- la collecte n'a probablement pas persiste."
            )
        elif source.active and source.last_collected_at is None:
            warnings.append(f"ℹ {source.name}: source active jamais collectee.")

    return rows, warnings


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "jamais"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--active-only", action="store_true", help="Ignorer les sources desactivees"
    )
    args = parser.parse_args()

    rows, warnings = build_report(args.active_only)

    name_width = max((len(r["name"]) for r in rows), default=10)
    print(
        f"{'Source':<{name_width}}  {'Actif':<6}{'Documents':>10}  {'Dernier doc':<18}  {'Derniere collecte':<18}"
    )
    print("-" * (name_width + 60))
    for r in rows:
        flag = "0 DOC!" if r["last_collected_at"] and r["document_count"] == 0 else ""
        print(
            f"{r['name']:<{name_width}}  {'oui' if r['active'] else 'non':<6}"
            f"{r['document_count']:>10}  {_format_dt(r['last_document_at']):<18}  "
            f"{_format_dt(r['last_collected_at']):<18}  {flag}"
        )

    print()
    if warnings:
        print(f"{len(warnings)} avertissement(s) :")
        for w in warnings:
            print(" ", w)
    else:
        print(
            "Aucun avertissement -- toutes les sources collectees ont bien des documents persistes."
        )

    # Code de sortie non-nul uniquement sur le vrai signal d'anomalie (0 doc
    # malgre last_collected_at) -- pas sur "jamais collectee", qui est un etat
    # normal pour une source fraichement ajoutee.
    hard_failures = [w for w in warnings if w.startswith("⚠")]
    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
