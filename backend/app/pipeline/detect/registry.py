"""Point d'entree unique de la couche detect : fait tourner tous les patterns
sur un texte et retourne leurs matches. Logique pure (voir CONTRIBUTING.md).

Chaque pattern (patterns/*.py) ne connait que le texte qu'on lui donne -- pas
le document source, pas la DB. C'est ici, au niveau du registre, qu'on associe
un RawMatch a son `document_id` pour produire un DetectionContract complet
(voir detect_all)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.contracts.detection import DetectionContract
from app.pipeline.detect.patterns.announcement import find_announcements
from app.pipeline.detect.patterns.api_key import find_api_keys
from app.pipeline.detect.patterns.card import find_cards
from app.pipeline.detect.patterns.credentials import find_credentials
from app.pipeline.detect.patterns.crypto_wallet import find_crypto_wallets
from app.pipeline.detect.patterns.distribution import find_distribution_channels
from app.pipeline.detect.patterns.domain import find_domains
from app.pipeline.detect.patterns.email import find_emails
from app.pipeline.detect.patterns.iban import find_ibans
from app.pipeline.detect.patterns.phone import find_phones
from app.pipeline.detect.patterns.threat_actor import find_threat_actors
from app.pipeline.detect.patterns.topic import find_source_topics
from app.pipeline.detect.patterns.victim import find_victims
from app.pipeline.detect.patterns.volume import find_volumes

# Detecteurs du chemin d'ingestion : deterministes (regex ou marqueur pose par
# la source), rapides, sans dependance a un modele.
#
# `find_organizations` (NER spaCy) en est volontairement ABSENT, alors qu'il y
# figurait initialement. Trois raisons constatees en usage reel :
#   - cout : ~69 ms/document, soit la quasi-totalite du temps de detect_all
#     (les 9 detecteurs regex reunis coutent quelques millisecondes) ;
#   - qualite : le NER remontait en tete du corpus du boilerplate de forum
#     ("Vuze, Utorrent", "Transmission") et du vocabulaire technique ("LLC",
#     "RAM", "SSH") plutot que des organisations reelles ;
#   - securite : il classait des adresses email entieres comme ORG, dont
#     `value_masked` est stocke EN CLAIR -- 68 PII brutes persistees en base
#     avant detection par integration/test_pipeline.py (regle non negociable
#     CONTRIBUTING.md §2).
#
# Le detecteur reste disponible a la demande pour la decouverte de candidats
# (voir api/routers/entities.py, POST /backfill-organizations) : c'est un outil
# d'exploration sous controle d'un analyste, pas un producteur de detections
# automatiques. Les victimes fiables viennent desormais de `find_victims`,
# qui lit ce que la source declare explicitement.
_DETECTORS = [
    find_emails,
    find_cards,
    find_ibans,
    find_crypto_wallets,
    find_api_keys,
    find_credentials,
    find_phones,
    find_domains,
    find_volumes,
    find_victims,
    find_threat_actors,
    find_source_topics,
    find_announcements,
]


def detect_all(
    text: str,
    document_id: uuid.UUID,
    is_relevant: bool = False,
    mentioned_urls: list[str] | None = None,
) -> list[DetectionContract]:
    """Fait tourner tous les detecteurs enregistres sur `text` et retourne les
    detections completes, pretes a persister (voir detection_repo).

    `mentioned_urls` : liens sortants deja extraits par la couche collect
    (`source_meta["mentioned_urls"]`, voir collect/link_extraction.py). Passe a
    part du texte parce que c'est une donnee deja structuree en amont -- la
    re-parser depuis `content` reviendrait a refaire moins bien un travail deja
    fait (voir patterns/distribution.py). Optionnel : tous les documents n'ont
    pas de liens sortants, et les appelants historiques n'ont pas a changer.

    Dedup par (type, value_hash) : un post de type "dox"/"combolist" repete
    souvent la meme valeur plusieurs fois (constate empiriquement -- un seul
    document a produit 8 detections identiques pour le meme email, une par
    mention dans le texte). Une valeur = une detection, peu importe son
    nombre d'occurrences dans le document -- l'information utile a l'analyste
    est "cette valeur apparait", pas "combien de fois".

    `is_relevant` : propage au niveau document (voir
    RawDocumentRepository.save_new_documents, ou le calcul se fait via
    keyword_match.py contre la watchlist active) -- detect_all lui-meme ne
    fait aucun matching, juste report cette info sur chaque detection
    produite pour permettre de filtrer le bruit hors-sujet (ex: dox de
    particulier sans rapport avec une organisation surveillee) sans jamais
    perdre la detection elle-meme (toujours persistee, voir CONTRIBUTING.md)."""
    now = datetime.now(timezone.utc)
    seen: set[tuple[str, str]] = set()
    detections = []

    raw_matches = [rm for detector in _DETECTORS for rm in detector(text)]
    if mentioned_urls:
        raw_matches.extend(find_distribution_channels(mentioned_urls))

    for raw_match in raw_matches:
        dedup_key = (raw_match.type.value, raw_match.value_hash)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        detections.append(
            DetectionContract(
                id=uuid.uuid4(),
                document_id=document_id,
                type=raw_match.type,
                value_masked=raw_match.value_masked,
                value_hash=raw_match.value_hash,
                validated=raw_match.validated,
                is_relevant=is_relevant,
                created_at=now,
            )
        )
    return detections
