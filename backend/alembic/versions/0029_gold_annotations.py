"""Echantillon de reference annote a la main.

Jusqu'ici, toutes les metriques du projet comparaient des classifieurs entre
eux (le modele aux regles) : elles mesuraient un ACCORD, jamais une JUSTESSE.
Un echantillon de 200 titres avait ete tire le 2026-08-29 dans des fichiers
CSV, mais jamais annote -- et le CSV ne montrait que le titre, alors que sur
un site de fuite le titre n'est souvent qu'une raison sociale nue.

Cette table porte l'echantillon, en base et dans l'application, avec le
document complet sous les yeux de l'annotateur.

Revision ID: 0029
Revises: 0028
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gold_annotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_documents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("control_rank", sa.Integer(), nullable=True),
        sa.Column("stratum", sa.String(), nullable=False),
        sa.Column("stratum_population", sa.Integer(), nullable=False),
        sa.Column("sampled_verdict", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("annotated_by", sa.String(), nullable=True),
        sa.Column("annotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("control_label", sa.String(), nullable=True),
        sa.Column("control_annotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gold_annotations_rank", "gold_annotations", ["rank"])


def downgrade() -> None:
    op.drop_index("ix_gold_annotations_rank", table_name="gold_annotations")
    op.drop_table("gold_annotations")
