"""Classification d'annonce sur les documents collectes.

Les forums generalistes produisent 20 a 96 % de bruit (tutoriels, entraide,
jeux pirates) la ou les sites de fuite dedies sont a 0 %. On persiste le
verdict du classifieur pour pouvoir FILTRER a l'affichage et EXCLURE du
calcul de gravite, sans jamais supprimer le document lui-meme.

Choix : colonnes NULLABLE. Les documents deja en base n'ont pas de verdict
tant qu'ils n'ont pas ete reclasses -- NULL signifie « jamais classe », pas
« non pertinent ». Ne jamais confondre les deux.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_documents",
        sa.Column("announcement_class", sa.String(), nullable=True),
    )
    op.add_column(
        "raw_documents",
        sa.Column("announcement_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "raw_documents",
        sa.Column("announcement_reason", sa.String(), nullable=True),
    )
    op.add_column(
        "raw_documents",
        sa.Column(
            "content_truncated",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    # Indexe : l'interface filtrera systematiquement dessus pour masquer le
    # bruit, et le calcul de gravite l'utilisera pour exclure NOISE.
    op.create_index(
        "ix_raw_documents_announcement_class",
        "raw_documents",
        ["announcement_class"],
    )


def downgrade() -> None:
    op.drop_index("ix_raw_documents_announcement_class", table_name="raw_documents")
    op.drop_column("raw_documents", "content_truncated")
    op.drop_column("raw_documents", "announcement_reason")
    op.drop_column("raw_documents", "announcement_score")
    op.drop_column("raw_documents", "announcement_class")
