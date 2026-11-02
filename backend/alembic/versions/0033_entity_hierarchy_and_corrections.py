"""Hiérarchie groupe / filiales, pays et secteur déclarés, corrections d'analyste.

Deux besoins, une migration (décision de projet, 2026-10-05) :

1. MULTINATIONALES. Acme a des filiales au Sénégal, au Mali, en Côte
   d'Ivoire… Chacune a ses domaines et son pays. `entities.parent_id` relie
   une filiale à son groupe (UN niveau : un groupe n'a pas lui-même de
   parent, contrôlé par le service). `country` / `sector` sont DÉCLARÉS par
   l'analyste et priment sur ceux d'un tiers (ransomware.live) pour les
   alertes de l'organisation.

2. CORRECTIONS D'ANALYSTE. Le pays d'Exemple Airports était donné au Kenya par
   ransomware.live au lieu de l'Égypte, et la passe horaire réécrivait toute
   correction faite en base. Les colonnes LUES PARTOUT (`severity`,
   `victim_country`, `victim_sector`) portent désormais la valeur EFFECTIVE ;
   `computed_*` garde ce que la plateforme a calculé, `*_override` ce que
   l'analyste a décidé, avec motif, auteur et date. Tri, filtres, PDF, STIX
   et Gouvernance continuent de lire les colonnes d'origine.

Revision ID: 0033
Revises: 0032
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entities", sa.Column("parent_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_entities_parent",
        "entities",
        "entities",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_entities_parent_id", "entities", ["parent_id"])
    op.add_column("entities", sa.Column("country", sa.String(length=2), nullable=True))
    op.add_column("entities", sa.Column("sector", sa.String(), nullable=True))

    for nom in ("computed_severity", "computed_country", "computed_sector"):
        op.add_column("alerts", sa.Column(nom, sa.String(), nullable=True))
    for nom in ("severity_override", "country_override", "sector_override"):
        op.add_column("alerts", sa.Column(nom, sa.String(), nullable=True))
    op.add_column("alerts", sa.Column("override_reason", sa.Text(), nullable=True))
    op.add_column("alerts", sa.Column("override_by", sa.String(), nullable=True))
    op.add_column(
        "alerts", sa.Column("override_at", sa.DateTime(timezone=True), nullable=True)
    )
    # L'existant : ce qui est en base EST le calcul (aucune correction n'existe).
    op.execute(
        "UPDATE alerts SET computed_severity = severity, "
        "computed_country = victim_country, computed_sector = victim_sector"
    )


def downgrade() -> None:
    for nom in (
        "override_at",
        "override_by",
        "override_reason",
        "sector_override",
        "country_override",
        "severity_override",
        "computed_sector",
        "computed_country",
        "computed_severity",
    ):
        op.drop_column("alerts", nom)
    op.drop_column("entities", "sector")
    op.drop_column("entities", "country")
    op.drop_index("ix_entities_parent_id", table_name="entities")
    op.drop_constraint("fk_entities_parent", "entities", type_="foreignkey")
    op.drop_column("entities", "parent_id")
