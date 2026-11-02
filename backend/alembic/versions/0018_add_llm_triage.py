"""Verdict LLM sur les annonces que les regles n'ont pas su trancher.

`announcement_filter.py` rend `uncertain` quand il ne trouve ni marqueur de
fuite franc, ni marqueur d'exclusion franc -- 728 documents, 18 % du corpus au
2026-09-03. Cette classe existe pour ne rien jeter en silence ; elle attendait
depuis le 2026-08-28 qu'un LLM la tranche.

⚠️ Colonnes SEPAREES, et `announcement_class` n'est jamais ecrase. Les regles
restent maitresses du chemin critique : elles sont reproductibles et
explicables, un LLM ne l'est pas. On veut pouvoir comparer les deux lectures,
pas remplacer l'une par l'autre -- et pouvoir tout effacer sans rien perdre.

⚠️ `llm_model` n'est pas decoratif : un verdict dont on ignore l'auteur n'est
pas auditable. Le meme document classe par deux modeles differents doit rester
distinguable, ne serait-ce que pour rejouer l'arbitrage apres un changement de
modele.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_documents", sa.Column("llm_class", sa.String(), nullable=True))
    op.add_column("raw_documents", sa.Column("llm_reason", sa.String(), nullable=True))
    op.add_column("raw_documents", sa.Column("llm_model", sa.String(), nullable=True))
    op.add_column(
        "raw_documents",
        sa.Column("llm_classified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Indexe : l'usage principal est « montre-moi ce que le LLM a requalifie »,
    # et le service repasse sur les documents encore sans verdict.
    op.create_index("ix_raw_documents_llm_class", "raw_documents", ["llm_class"])


def downgrade() -> None:
    op.drop_index("ix_raw_documents_llm_class", table_name="raw_documents")
    op.drop_column("raw_documents", "llm_classified_at")
    op.drop_column("raw_documents", "llm_model")
    op.drop_column("raw_documents", "llm_reason")
    op.drop_column("raw_documents", "llm_class")
