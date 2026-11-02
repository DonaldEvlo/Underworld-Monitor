"""Isolation des tests d'integration : AUCUNE ecriture ne survit a un test.

POURQUOI. Ces tests tournent contre la base de developpement (il n'existe pas
de base de test separee) et commitaient pour de vrai. Consequences constatees,
quatre fois : un test a reecrit la severite des 33 alertes reelles
(2026-09-15), un autre a cree une vraie alerte regionale de 20 victimes
(2026-09-02), et une entite de test (`Test entity doublon-victime.tld`) est
restee active dans la watchlist. Le nettoyage manuel en fin de test ne
s'execute pas quand le test echoue avant.

COMMENT. Pour chaque test : une connexion, une transaction englobante, et
`SessionLocal` rattache a cette connexion en mode `create_savepoint`. Les
`commit()` du code teste -- services, depots, routes FastAPI via `get_db` --
ne valident plus qu'un point de sauvegarde ; la transaction englobante est
ANNULEE a la fin. Les donnees reelles restent lisibles (plusieurs tests en
dependent), seules les ecritures disparaissent.

⚠️ `SessionLocal.configure(...)` agit sur l'OBJET fabrique, pas sur un nom :
cela couvre aussi les modules qui ont fait `from app.db.session import
SessionLocal` a l'import. Remplacer l'attribut du module ne suffirait pas.

⚠️ Limite : du code qui ouvrirait sa propre connexion via `engine` echapperait
a l'isolation. Verifie le 2026-09-25 : aucun module applicatif ne le fait.
"""

from __future__ import annotations

import pytest

from app.db.session import SessionLocal, engine


@pytest.fixture(autouse=True)
def transaction_annulee():
    connexion = engine.connect()
    transaction = connexion.begin()
    SessionLocal.configure(bind=connexion, join_transaction_mode="create_savepoint")
    try:
        yield connexion
    finally:
        # Restaurer AVANT de fermer : un test suivant hors de ce repertoire
        # doit retrouver la fabrique d'origine.
        SessionLocal.configure(
            bind=engine, join_transaction_mode="conservative_savepoint"
        )
        transaction.rollback()
        connexion.close()
