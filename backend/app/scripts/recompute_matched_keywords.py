"""Recalcule raw_documents.matched_keywords sur tout l'historique deja
collecte, avec la watchlist actuelle (voir seed_watchlist_leak_terms.py --
la watchlist a ete enrichie apres la collecte de la plupart des documents
existants, leur matched_keywords fige au moment de l'ecriture est donc
obsolete, voir document_repo.save_new_documents).

A executer apres tout enrichissement de la watchlist si on veut que
l'historique en beneficie (sinon seuls les nouveaux documents collectes
matcheront les nouveaux termes).

Usage : python -m app.scripts.recompute_matched_keywords
"""

from app.db.models.raw_document import RawDocument
from app.db.session import SessionLocal
from app.pipeline.detect.keyword_match import find_keyword_matches
from app.repositories.keyword_repo import KeywordRepository

if __name__ == "__main__":
    db = SessionLocal()
    watchlist_terms = KeywordRepository(db).get_active_terms()
    print(f"{len(watchlist_terms)} terme(s) actif(s) dans la watchlist")

    docs = db.query(RawDocument).all()
    print(f"{len(docs)} document(s) a retraiter")

    now_matched = 0
    for doc in docs:
        matches = find_keyword_matches(doc.content, watchlist_terms)
        doc.matched_keywords = matches or None
        if matches:
            now_matched += 1
    db.commit()

    print(f"{now_matched} document(s) matchent au moins un terme de la watchlist")
