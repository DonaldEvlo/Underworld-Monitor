"""Alertes de perimetre GEOGRAPHIQUE, sans entite declaree.

Jusqu'ici une victime ne declenchait une alerte que si quelqu'un l'avait
declaree dans la watchlist. Mesure du 2026-09-02 : la collecte trouve
**3101 domaines de victimes, dont 31 surveilles** -- 1 % de conversion. Le
goulot n'etait plus la collecte mais la declaration.

Une alerte peut desormais porter soit sur une entite (`scope='entity'`, le
comportement existant, inchange), soit sur une REGION (`scope='region'`) : une
victime situee dans un perimetre geographique surveille alerte meme si
personne ne l'a declaree. Gain concret mesure : `suivi-flotte.co.za` (Afrique du
Sud) et `mutuelle-exemple.co.zw` (Zimbabwe), deux vraies victimes africaines
publiees par un site de fuite et que rien ne signalait.

⚠️ `entity_id` devient NULLABLE. C'est la seule facon d'exprimer une alerte
sans entite ; la contrainte d'unicite (entity_id, alert_date) est remplacee
par deux index partiels, un par portee, pour que l'idempotence tienne dans les
deux cas. En Postgres, un UNIQUE ordinaire sur une colonne NULL ne contraint
rien -- deux alertes regionales du meme jour auraient pu coexister.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("alerts", "entity_id", existing_type=sa.UUID(), nullable=True)
    op.add_column(
        "alerts",
        sa.Column("scope", sa.String(), nullable=False, server_default="entity"),
    )
    op.add_column("alerts", sa.Column("region", sa.String(), nullable=True))

    op.drop_constraint("uq_alerts_entity_id_alert_date", "alerts", type_="unique")
    # Index partiels : l'unicite d'une alerte d'entite reste (entite, jour), et
    # celle d'une alerte regionale devient (region, jour). Un UNIQUE unique sur
    # les deux colonnes ne conviendrait pas, `entity_id` etant NULL pour l'une
    # et `region` NULL pour l'autre.
    op.create_index(
        "uq_alerts_entity_date",
        "alerts",
        ["entity_id", "alert_date"],
        unique=True,
        postgresql_where=sa.text("entity_id IS NOT NULL"),
    )
    op.create_index(
        "uq_alerts_region_date",
        "alerts",
        ["region", "alert_date"],
        unique=True,
        postgresql_where=sa.text("region IS NOT NULL"),
    )
    op.create_index("ix_alerts_scope", "alerts", ["scope"])


def downgrade() -> None:
    op.drop_index("ix_alerts_scope", table_name="alerts")
    op.drop_index("uq_alerts_region_date", table_name="alerts")
    op.drop_index("uq_alerts_entity_date", table_name="alerts")
    # Les alertes regionales n'ont pas d'entite : les retirer avant de rendre
    # la colonne obligatoire, sans quoi la migration inverse echoue.
    op.execute(
        "DELETE FROM alert_detections WHERE alert_id IN "
        "(SELECT id FROM alerts WHERE entity_id IS NULL)"
    )
    op.execute("DELETE FROM alerts WHERE entity_id IS NULL")
    op.drop_column("alerts", "region")
    op.drop_column("alerts", "scope")
    op.alter_column("alerts", "entity_id", existing_type=sa.UUID(), nullable=False)
    op.create_unique_constraint(
        "uq_alerts_entity_id_alert_date", "alerts", ["entity_id", "alert_date"]
    )
