"""Roles utilisateurs + journal des acces aux alertes.

Deux manques structurels traites ensemble parce qu'ils n'en font qu'un : sans
role, « qui a consulte » ne veut rien dire ; sans journal, un role n'est qu'une
gene a l'usage.

⚠️ AVANT : `users` ne portait aucun role -- **tout utilisateur authentifie
accedait aux 80 endpoints**, y compris vider les alertes et supprimer une
source. Les trois profils du dossier de conception decrivaient une cible, pas
l'implementation.

⚠️ LA REGLE 5 (« minimisation & tracabilite ») EXIGE LA JOURNALISATION DES
ACCES AUX ALERTES et n'avait **aucune** implementation -- aucune table d'audit
dans les 9 tables metier. C'etait une intention, pas un dispositif.

⚠️ MIGRATION DES COMPTES EXISTANTS : ils passent en `admin`, pas en `analyst`.
Motif mesure : la base ne contient qu'un compte, `admin`, qui est celui du
responsable et administre reellement la plateforme. Le rabattre en `analyst` le
priverait de ses propres reglages au premier deploiement. Le DEFAUT pour un
compte NOUVEAU reste `analyst` (moindre privilege) -- les deux choix ne sont
pas contradictoires : l'un constate l'existant, l'autre borne l'avenir.

Revision ID: 0027
Revises: 0026
"""

from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ajoutee NULLABLE puis remplie puis contrainte : un ALTER direct en NOT
    # NULL echoue des qu'une ligne existe.
    op.add_column("users", sa.Column("role", sa.String(), nullable=True))
    op.execute("UPDATE users SET role = 'admin' WHERE role IS NULL")
    op.alter_column("users", "role", nullable=False, server_default="analyst")

    op.create_table(
        "alert_accesses",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        # ⚠️ `username` et `role` sont RECOPIES, pas seulement references.
        # Un compte renomme ou dont le role change ne doit pas reecrire
        # l'histoire : le journal doit dire ce qui etait vrai AU MOMENT de
        # l'acces. Une jointure sur `users` afficherait le role d'aujourd'hui.
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("alert_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_accesses_user_id", "alert_accesses", ["user_id"])
    op.create_index("ix_alert_accesses_alert_id", "alert_accesses", ["alert_id"])
    op.create_index("ix_alert_accesses_accessed_at", "alert_accesses", ["accessed_at"])


def downgrade() -> None:
    op.drop_index("ix_alert_accesses_accessed_at", table_name="alert_accesses")
    op.drop_index("ix_alert_accesses_alert_id", table_name="alert_accesses")
    op.drop_index("ix_alert_accesses_user_id", table_name="alert_accesses")
    op.drop_table("alert_accesses")
    op.drop_column("users", "role")
