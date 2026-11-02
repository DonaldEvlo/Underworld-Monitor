"""Purge et regenere toutes les detections avec le code corrige (dedup par
(type, value_hash) au sein d'un document, mask_domain lisible pour les
domaines, email normalise en minuscule avant hash, is_relevant calcule contre
la watchlist). L'historique produit par l'ancien code melangeait doublons non
dedupliques, masquage illisible sur les domaines courts, et n'avait pas
encore la notion de pertinence -- repart sur une base propre plutot que de
patcher au cas par cas.

is_relevant reutilise raw_documents.matched_keywords (deja calcule a la
collecte, voir save_new_documents) plutot que de refaire le matching --
meme resultat, pas besoin de refetcher la watchlist active.

Usage : python -m app.scripts.rebuild_detections
"""

from app.db.models.raw_document import RawDocument
from app.db.session import SessionLocal
from app.pipeline.detect.registry import detect_all
from app.repositories.detection_repo import DetectionRepository

if __name__ == "__main__":
    db = SessionLocal()
    repo = DetectionRepository(db)

    old_count = repo.delete_all()
    print(f"{old_count} ancienne(s) detection(s) supprimee(s)")

    docs = db.query(RawDocument).all()
    print(f"{len(docs)} document(s) a retraiter")

    all_detections = []
    for doc in docs:
        is_relevant = bool(doc.matched_keywords)
        all_detections.extend(detect_all(doc.content, doc.id, is_relevant=is_relevant))

    repo.save_all(all_detections)
    print(f"{len(all_detections)} nouvelle(s) detection(s) persistee(s)")
    relevant = sum(1 for d in all_detections if d.is_relevant)
    print(f"dont {relevant} marquee(s) pertinente(s) (watchlist)")
