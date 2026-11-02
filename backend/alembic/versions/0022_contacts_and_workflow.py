"""Destinataires des alertes, trace d'envoi, et travail a plusieurs.

⚠️ COMBLE LE MANQUE CENTRAL DU PRODUIT. Le livrable est « prevenir
l'organisation », or aucune entite ne portait de contact : le destinataire
etait une adresse unique dans `.env` (`ALERT_EMAIL_TO`), la meme pour les 42
organisations surveillees. Le systeme detectait parfaitement et ne savait pas
a qui parler.

Trois apports :
  - `entity_contacts` : a QUI l'alerte doit partir, par organisation ;
  - `alert_notifications` : ce qui a REELLEMENT ete envoye, a qui, quand, par
    qui -- sans cette trace, « prevenue » n'est pas verifiable ;
  - qualification et affectation sur `alerts` : ecarter un faux positif doit
    etre distinguable d'un incident traite, sinon la donnee est perdue pour
    ajuster les regles plus tard.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=False),
        # CERT, RSSI, DPO... texte libre : les intitules varient trop d'une
        # organisation a l'autre pour une enumeration.
        sa.Column("role", sa.String(), nullable=True),
        # ⚠️ Un seul contact principal par entite : c'est lui qui recoit par
        # defaut. Sans designation, l'envoi devrait deviner.
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("entity_id", "email", name="uq_entity_contact_email"),
    )

    op.create_table(
        "alert_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "alert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("recipient", sa.String(), nullable=False),
        # "email" aujourd'hui ; la colonne existe pour qu'un futur canal
        # (webhook) n'exige pas une migration de plus.
        sa.Column("channel", sa.String(), nullable=False, server_default="email"),
        # "sent" | "failed" -- un echec doit rester TRACE : croire qu'une
        # organisation a ete prevenue alors qu'elle ne l'a pas ete est pire
        # que de ne pas avoir essaye.
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        # Qui a declenche l'envoi : `NULL` = envoi automatique.
        sa.Column("sent_by", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- Qualification et affectation ------------------------------------
    op.add_column("alerts", sa.Column("assignee", sa.String(), nullable=True))
    op.add_column("alerts", sa.Column("analyst_note", sa.Text(), nullable=True))
    # `confirmed` | `false_positive` | `duplicate` | `out_of_scope`
    #
    # ⚠️ Sans ce champ, « faux positif ecarte » et « incident reel traite »
    # sont le meme etat `resolved` : l'historique des faux positifs -- la
    # seule matiere qui permettrait d'ajuster les seuils -- est perdu.
    op.add_column("alerts", sa.Column("resolution_reason", sa.String(), nullable=True))
    op.add_column(
        "alerts",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alerts", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "alerts",
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    for colonne in (
        "last_notified_at",
        "resolved_at",
        "acknowledged_at",
        "resolution_reason",
        "analyst_note",
        "assignee",
    ):
        op.drop_column("alerts", colonne)
    op.drop_table("alert_notifications")
    op.drop_table("entity_contacts")
