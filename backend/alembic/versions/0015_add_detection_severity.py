"""Severite persistee sur la detection.

Jusqu'ici la severite n'existait que dans le chemin d'alerting, calculee a la
volee et jamais conservee. Consequence : une victime qui ne correspond a aucune
entite surveillee n'en avait aucune -- `alert_service` fait `continue` avant
meme d'appeler `severity_for_detection`.

Or ces victimes existent et sont reelles : mesure du 2026-09-01, 65 detections
sont corroborees par un observateur independant AVEC attribution de gang, dont
61 concernent des organisations que nous ne surveillons pas (`alarmes-exemple.com` /
lockbit5, `industry.airliquide.kr` / safepay, `labo-exemple.com` / krybit...).
RansomLook en couvre ~1000 au total.

Decision du 2026-09-01 : la severite devient un attribut de la DETECTION, pas
seulement de l'alerte. Une institution hors perimetre porte donc une severite,
meme si elle ne declenche pas d'alerte -- l'alerte reste reservee aux entites
surveillees (`alerts.entity_id` demeure NOT NULL).

⚠️ Colonne NULLABLE a dessein. NULL signifie « pas encore evaluee », pas
« aucune severite » -- meme distinction que `corroboration_status` NULL, qui
est une absence de mesure et non un resultat negatif. Une detection ingeree
entre deux passes porte NULL jusqu'au prochain recalcul.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("detections", sa.Column("severity", sa.String(), nullable=True))
    # Indexe : la valeur d'usage de cette colonne est le tri et le filtrage de
    # la page Detections sur un corpus de plus de 20 000 lignes.
    op.create_index("ix_detections_severity", "detections", ["severity"])


def downgrade() -> None:
    op.drop_index("ix_detections_severity", table_name="detections")
    op.drop_column("detections", "severity")
