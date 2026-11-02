"""Duree de la derniere collecte, par source.

Sans elle, aucune estimation de temps n'est possible pendant une collecte :
l'interface affichait « 7/24 sources » sans dire combien de temps il restait.

⚠️ La DERNIERE duree, pas une moyenne. C'est volontaire et il faut le savoir en
la lisant : les durees varient fortement d'une passe a l'autre sur .onion
(mesure du 2026-08-21 : DARKNET ARMY entre 1292 et 1481 s selon la passe). Une
moyenne lissee masquerait cette variabilite ; une derniere valeur, elle, se lit
pour ce qu'elle est -- un ordre de grandeur, pas une promesse.

Renseignee aussi bien sur succes que sur echec : une source injoignable coute
du temps (delais d'attente), et l'ignorer sous-estimerait systematiquement
l'estimation restante.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("last_collection_duration_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "last_collection_duration_seconds")
