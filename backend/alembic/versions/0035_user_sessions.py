"""Sessions côté serveur : déconnexion réelle, expiration par inactivité.

La déconnexion n'existait que dans le navigateur ; le jeton de
rafraîchissement (7 jours) restait utilisable après « Se déconnecter », un
changement de mot de passe ou de rôle. Chaque jeton porte désormais
l'identifiant de sa session, révocable côté serveur.

⚠️ Les jetons émis avant cette migration n'ont pas d'identifiant de session :
ils sont refusés, les utilisateurs connectés doivent se reconnecter une fois.

Revision ID: 0035
Revises: 0034
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(), nullable=True),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_id", "user_sessions")
    op.drop_table("user_sessions")
