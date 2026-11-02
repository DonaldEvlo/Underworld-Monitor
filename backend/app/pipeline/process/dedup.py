"""Detection de quasi-doublons (reposts legerement modifies -- horodatage,
en-tete de forum, un mot change) via SimHash. Logique pure (voir CONTRIBUTING.md).

Le hash exact (content_hash, deja gere dans document_repo.save_new_documents)
ne suffit pas : un meme leak repost sur plusieurs threads/sources avec un titre
ou un timestamp different produit un hash exact totalement different alors que
le contenu est quasiment identique. SimHash resout ca : deux textes proches
produisent des empreintes dont la distance de Hamming est petite, meme si le
hash exact differe completement.

Implementation maison (pas de lib dediee) : l'algorithme tient en quelques
lignes (hash de shingles + vote bit-a-bit) et evite une dependance externe
pour ce qui reste un hash simple, pas un modele ML."""

import hashlib
import re

# 63 bits (pas 64) pour que l'empreinte tienne dans un BigInteger PostgreSQL
# (signe, plage -2^63..2^63-1) sans conversion signe/non-signe a l'ecriture/
# lecture -- perte de precision negligeable pour une empreinte de similarite.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_HASH_BITS = 63

# Distance de Hamming (sur 63 bits) en-dessous de laquelle deux documents sont
# consideres quasi-duplicats. Calibre sur un cas realiste (voir conversation
# projet) : un repost akira avec corps identique mais titre/date/mention de
# source differents mesure ~10 ; deux victimes differentes non liees mesurent
# ~38. Seuil place nettement sous l'ecart observe, pas au hasard -- a re-verifier
# si le corpus reel produit des faux positifs/negatifs une fois en usage.
DEFAULT_HAMMING_THRESHOLD = 15


def _shingles(text: str, size: int = 4) -> list[str]:
    """Suites de `size` mots consecutifs (shingles) -- unite sur laquelle porte
    le hash, plus robuste qu'un hash mot-a-mot face a un reordonnancement local
    (ex: une phrase d'intro ajoutee en tete d'un repost)."""
    tokens = _TOKEN_RE.findall(text.lower())
    if len(tokens) < size:
        return [" ".join(tokens)] if tokens else []
    return [" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)]


def compute_simhash(text: str) -> int | None:
    """Calcule l'empreinte SimHash (64 bits) de `text`, ou None si le texte est
    vide/trop court pour produire un shingle."""
    shingles = _shingles(text)
    if not shingles:
        return None

    bit_votes = [0] * _HASH_BITS
    for shingle in shingles:
        shingle_hash = int(
            hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).hexdigest(), 16
        )
        for bit in range(_HASH_BITS):
            if shingle_hash & (1 << bit):
                bit_votes[bit] += 1
            else:
                bit_votes[bit] -= 1

    fingerprint = 0
    for bit, vote in enumerate(bit_votes):
        if vote > 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def is_near_duplicate(
    simhash: int,
    existing_simhashes: list[int],
    threshold: int = DEFAULT_HAMMING_THRESHOLD,
) -> bool:
    """True si `simhash` est a distance de Hamming <= `threshold` d'au moins
    une empreinte de `existing_simhashes` (deja vues pour la meme source, ou
    plus largement selon ce que l'appelant fournit)."""
    return any(
        hamming_distance(simhash, existing) <= threshold
        for existing in existing_simhashes
    )
