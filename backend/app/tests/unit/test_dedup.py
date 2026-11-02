"""Tests de la deduplication near-duplicate (voir pipeline/process/dedup.py).

Ce que ces tests protegent : un meme leak reposte sur plusieurs threads ou
sources produit un `content_hash` totalement different (un titre ou un
horodatage suffit), alors que le contenu est le meme. Sans SimHash, l'analyste
verrait le meme incident plusieurs fois -- exactement le bruit que la
selectivite attendue cherche a eviter.

Les tests portent sur les proprietes de l'algorithme (stabilite, sensibilite,
symetrie) plutot que sur des valeurs d'empreinte codees en dur : ces valeurs
dependent de l'implementation du hash et changeraient a la moindre evolution,
sans rien dire de la correction du comportement."""

from app.pipeline.process.dedup import (
    DEFAULT_HAMMING_THRESHOLD,
    compute_simhash,
    hamming_distance,
    is_near_duplicate,
)

_ANNOUNCEMENT = (
    "Acme Corporation has been compromised. The full customer database is now "
    "available for download, including names, email addresses and hashed "
    "passwords. Contact us on the forum for the download link and pricing."
)


class TestComputeSimhash:
    def test_is_deterministic(self):
        assert compute_simhash(_ANNOUNCEMENT) == compute_simhash(_ANNOUNCEMENT)

    def test_returns_none_for_empty_text(self):
        assert compute_simhash("") is None
        assert compute_simhash("   \n\t ") is None

    def test_handles_text_shorter_than_shingle_size(self):
        """Moins de 4 mots : le texte entier devient un seul shingle plutot que
        de renvoyer None -- un titre court reste comparable."""
        assert compute_simhash("Acme breached") is not None

    def test_fits_in_a_postgres_bigint(self):
        """L'empreinte est persistee en BigInteger signe (voir migration 0007) :
        elle doit tenir sur 63 bits, sans quoi l'ecriture echouerait."""
        fingerprint = compute_simhash(_ANNOUNCEMENT)
        assert 0 <= fingerprint < 2**63

    def test_is_case_insensitive(self):
        """La casse ne change pas le sens d'une annonce : un repost en
        majuscules reste le meme contenu."""
        assert compute_simhash(_ANNOUNCEMENT) == compute_simhash(_ANNOUNCEMENT.upper())


class TestHammingDistance:
    def test_identical_values_have_zero_distance(self):
        assert hamming_distance(0b1011, 0b1011) == 0

    def test_counts_differing_bits(self):
        assert hamming_distance(0b0000, 0b1111) == 4
        assert hamming_distance(0b1010, 0b1011) == 1

    def test_is_symmetric(self):
        a, b = 0b110010, 0b101011
        assert hamming_distance(a, b) == hamming_distance(b, a)


class TestNearDuplicateDetection:
    def test_repost_with_minor_edits_is_detected(self):
        """Cas reel vise : meme annonce avec un horodatage et un en-tete de
        forum ajoutes. Le content_hash differerait totalement."""
        repost = "[2026-08-14 09:12] Reposted from another forum.\n" + _ANNOUNCEMENT
        original = compute_simhash(_ANNOUNCEMENT)
        variant = compute_simhash(repost)
        assert hamming_distance(original, variant) <= DEFAULT_HAMMING_THRESHOLD
        assert is_near_duplicate(variant, [original]) is True

    def test_unrelated_announcements_are_not_confused(self):
        """Contrepartie indispensable : deux victimes differentes ne doivent
        jamais etre fusionnees, sinon on perdrait une vraie alerte."""
        other = (
            "Globex Industries payment gateway logs are for sale. Includes "
            "transaction identifiers, merchant references and internal API "
            "endpoints used by their billing platform."
        )
        assert (
            is_near_duplicate(compute_simhash(other), [compute_simhash(_ANNOUNCEMENT)])
            is False
        )

    def test_identical_text_is_always_a_duplicate(self):
        fingerprint = compute_simhash(_ANNOUNCEMENT)
        assert is_near_duplicate(fingerprint, [fingerprint]) is True

    def test_no_existing_fingerprints_means_no_duplicate(self):
        assert is_near_duplicate(compute_simhash(_ANNOUNCEMENT), []) is False

    def test_matches_against_any_fingerprint_in_the_list(self):
        """Le doublon peut correspondre a n'importe quel document deja vu, pas
        seulement au dernier."""
        target = compute_simhash(_ANNOUNCEMENT)
        others = [compute_simhash("Completely different content about nothing"), target]
        assert is_near_duplicate(target, others) is True

    def test_threshold_is_configurable(self):
        """Un seuil a 0 n'accepte que l'identite stricte -- utile si le corpus
        reel revelait des faux positifs au seuil par defaut."""
        variant = compute_simhash(_ANNOUNCEMENT + " Extra sentence added here.")
        original = compute_simhash(_ANNOUNCEMENT)
        assert is_near_duplicate(variant, [original], threshold=0) is (
            variant == original
        )
