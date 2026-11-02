"""Journalisation des acces aux alertes -- regle 5 (« minimisation &
tracabilite »), qui n'avait jusqu'ici AUCUNE implementation.

⚠️ ON JOURNALISE L'ACCES, PAS LE CONTENU. La ligne porte un utilisateur, une
alerte, une action, un horodatage. Ni valeur, ni extrait, ni domaine :
journaliser le contenu consulte recreerait une seconde copie de la PII qu'on
s'interdit de stocker (regle 2) -- le journal deviendrait le probleme qu'il
documente.

⚠️ NE FAIT JAMAIS ECHOUER LA LECTURE D'UNE ALERTE. Meme doctrine que la
corroboration et les renseignements par victime : le livrable est l'alerte. Un
journal indisponible degrade la tracabilite, il ne doit pas priver l'analyste
de son poste de travail -- sinon la premiere panne de base transforme une
mesure de conformite en panne de production.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.core.roles import role_de
from app.db.models.alert_access import AlertAccess
from app.db.models.user import User

logger = logging.getLogger(__name__)

# Actions journalisees. `list` compte autant que `read` : consulter la file
# expose deja des noms d'organisations victimes.
ACTIONS = ("list", "read", "report", "export")


def journaliser_acces(
    db: Session,
    utilisateur: User | None,
    action: str,
    *,
    alert_id: uuid.UUID | None = None,
) -> None:
    """Enregistre un acces. Silencieux en cas d'echec, par conception."""
    if utilisateur is None or action not in ACTIONS:
        return
    try:
        db.add(
            AlertAccess(
                id=uuid.uuid4(),
                user_id=utilisateur.id,
                # ⚠️ `username` et `role` sont RECOPIES, pas joints : le
                # journal doit dire ce qui etait vrai AU MOMENT de l'acces.
                # Une jointure sur `users` afficherait le role d'aujourd'hui,
                # et un compte renomme reecrirait l'histoire.
                username=utilisateur.username,
                role=role_de(utilisateur.role).value,
                alert_id=alert_id,
                action=action,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Journal des acces aux alertes indisponible", exc_info=True)
