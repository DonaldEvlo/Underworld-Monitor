"""Le journal des acces ne doit plus empecher de supprimer un compte.

⚠️ DEFAUT TROUVE EN NETTOYANT, PAS PAR UN TEST. La migration `0027` posait
`alert_accesses.user_id` en `NOT NULL` avec une cle etrangere SANS action de
suppression. Consequence non voulue : **supprimer un utilisateur devenait
impossible** des qu'il avait consulte une seule alerte (violation de cle
etrangere). Constate en tentant de retirer les trois comptes de test.

L'intention etait bonne -- « un compte supprime ne doit pas effacer la trace
de ce qu'il a consulte » -- mais le moyen etait faux : elle interdisait la
suppression au lieu de preserver la trace.

→ `user_id` devient NULLABLE avec `ON DELETE SET NULL`. La trace survit parce
que `username` et `role` sont RECOPIES dans la ligne (decision de `0027`,
prise pour une autre raison : dire ce qui etait vrai au moment de l'acces).
C'est cette copie qui rend le detachement possible sans perte.

ℹ️ Le journal garde donc des lignes dont l'auteur n'existe plus, avec son nom
et son role d'alors. C'est le comportement attendu d'un journal d'audit.

Revision ID: 0028
Revises: 0027
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_FK = "alert_accesses_user_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK, "alert_accesses", type_="foreignkey")
    op.alter_column("alert_accesses", "user_id", nullable=True)
    op.create_foreign_key(
        _FK, "alert_accesses", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "alert_accesses", type_="foreignkey")
    # ⚠️ Les lignes detachees (user_id NULL) empechent le retour a NOT NULL :
    # on les retire, c'est le prix d'un downgrade. Le journal est fait pour
    # avancer, pas pour revenir en arriere.
    op.execute("DELETE FROM alert_accesses WHERE user_id IS NULL")
    op.alter_column("alert_accesses", "user_id", nullable=False)
    op.create_foreign_key(_FK, "alert_accesses", "users", ["user_id"], ["id"])
