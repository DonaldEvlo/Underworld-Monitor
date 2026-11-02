"""Alerte regionale : une par VICTIME, plus une par (region, jour).

Mesure du 2026-09-30 : l'alerte « Afrique » du 29/09 regroupait 14 victimes
sous UNE gravite (`medium`). La Exemple Defence Force (Government & Defense,
attaque du 12/09, moins de 30 jours) y etait noyee alors que seule elle aurait
ete CRITICAL. Gravite, credibilite, notation Admiralty, date d'attaque et
resume sont portes par l'ALERTE : les calculer sur un agregat de victimes
revenait a ne les calculer pour aucune.

`victim_key` = victime normalisee (`normalize_victim` : domaine de preference,
sinon raison sociale). L'unicite regionale devient (region, victime, jour).

Les alertes regionales anterieures gardent `victim_key` NULL. En Postgres, des
NULL ne se contredisent pas dans un index unique : elles restent valides.

Revision ID: 0032
Revises: 0031
"""

from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("victim_key", sa.String(), nullable=True))
    op.drop_index("uq_alerts_region_date", table_name="alerts")
    op.create_index(
        "uq_alerts_region_victim_date",
        "alerts",
        ["region", "victim_key", "alert_date"],
        unique=True,
        postgresql_where=sa.text("region IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_region_victim_date", table_name="alerts")
    # ⚠️ Echoue si plusieurs alertes regionales partagent (region, jour) --
    # c'est-a-dire apres toute scission. Il faudrait d'abord les regrouper :
    # un retour arriere ne doit pas detruire de decisions d'analyste en silence.
    op.create_index(
        "uq_alerts_region_date",
        "alerts",
        ["region", "alert_date"],
        unique=True,
        postgresql_where=sa.text("region IS NOT NULL"),
    )
    op.drop_column("alerts", "victim_key")
