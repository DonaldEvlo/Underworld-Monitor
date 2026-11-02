"""Renseignements par victime (ransomware.live) sur les alertes.

Alimente les criteres de criticite demandes qui n'avaient AUCUNE source
jusqu'ici : date reelle de l'attaque, secteur, et exposition d'identifiants.

⚠️ AUCUNE PII. Ces colonnes ne portent que des COMPTEURS, des DATES et des
LIBELLES -- jamais un identifiant, une adresse ou un mot de passe. Verifie sur
le payload reel (2026-09-15) : `employees`/`users`/`thirdparties` sont des
entiers, `last_*_compromised` des dates ISO. Meme forme que le booleen
`known_breached` de HIBP : on enregistre COMBIEN et DEPUIS QUAND, jamais QUI.
Verrouille cote code par `test_victim_intel.TestAucunePII`.

⚠️ `intel_refreshed_at` N'EST PAS DECORATIF. Sans lui, `compromised_users = 0`
serait indiscernable de « jamais mesure ». Meme convention que
`corroboration_status` NULL et `severity` NULL : une absence de mesure n'est
pas un resultat negatif. Tant que `intel_refreshed_at` est NULL, les compteurs
ne veulent rien dire et ne doivent alimenter aucun calcul.

Revision ID: 0026
Revises: 0025
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


# (nom, type) -- ajoutees a `alerts`, le livrable du produit.
_COLONNES = [
    # Date REELLE de l'attaque telle que documentee par un tiers. Mesure :
    # 22 % de nos documents d'alerte sont dates contre 29/29 ici.
    # ⚠️ Les dates d'INDEXATION EN LOT sont ecartees en amont
    # (`batch_indexing_dates`) : 44 % des victimes APT73 partageaient une
    # meme fausse date. Une date fausse est pire qu'une date absente.
    ("victim_attack_date", sa.DateTime(timezone=True)),
    # Secteur declare (« Government & Defense », « Healthcare »...). Porte
    # gratuitement la distinction publique/privee demandee -- aucun champ a
    # saisir par l'analyste.
    ("victim_sector", sa.String()),
    ("victim_country", sa.String()),
    # Exposition aux logs de voleurs d'identifiants, en COMPTEURS.
    # `employees` = personnel de l'organisation, `users` = ses clients,
    # `thirdparties` = prestataires. La distinction porte sur le ROLE
    # vis-a-vis de l'organisation, JAMAIS sur la personne (precedent DOXBYTE
    # : « citoyen simple » ne doit pas devenir un axe de gravite).
    ("compromised_employees", sa.Integer()),
    ("compromised_users", sa.Integer()),
    ("compromised_thirdparties", sa.Integer()),
    # Familles de logiciel voleur citees (RedLine, Lumma, Raccoon...). C'est
    # de la METHODE au niveau de l'organisation -- pas un operateur, pas une
    # personne.
    ("stealer_families", JSONB()),
    ("last_employee_compromised", sa.DateTime(timezone=True)),
    ("last_user_compromised", sa.DateTime(timezone=True)),
    # Horodatage de la MESURE elle-meme -- voir l'avertissement en tete.
    ("intel_refreshed_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    for nom, type_ in _COLONNES:
        op.add_column("alerts", sa.Column(nom, type_, nullable=True))
    # Le tri et le filtrage par fraicheur de l'incident sont le nouvel axe de
    # criticite : sans index, chaque passe de severite balaierait la table.
    op.create_index("ix_alerts_victim_attack_date", "alerts", ["victim_attack_date"])


def downgrade() -> None:
    op.drop_index("ix_alerts_victim_attack_date", table_name="alerts")
    for nom, _ in reversed(_COLONNES):
        op.drop_column("alerts", nom)
