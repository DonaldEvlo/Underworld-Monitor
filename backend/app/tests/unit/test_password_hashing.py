"""Tests de masking.hash_password (HMAC-SHA256 poivre) et de son usage dans
le pattern credentials.

Ce que ces tests protegent : un mot de passe a une entropie faible, un
SHA-256 nu est reversible par dictionnaire. Le poivre (hors base) est la
seule chose qui empeche un dump de `detections` d'etre attaquable."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from app.pipeline.detect.masking import hash_password, hash_value
from app.pipeline.detect.patterns.credentials import find_credentials

_PEPPER = "poivre-de-test"


class TestHashPassword:
    @patch("app.pipeline.detect.masking.settings")
    def test_is_not_a_plain_sha256(self, settings):
        """La regression a eviter : revenir a un SHA-256 nu, cassable par
        rainbow table."""
        settings.PASSWORD_HASH_PEPPER = _PEPPER
        password = "azerty123"

        assert hash_password(password) != hashlib.sha256(password.encode()).hexdigest()
        assert hash_password(password) != hash_value(password)

    @patch("app.pipeline.detect.masking.settings")
    def test_depends_on_the_pepper(self, settings):
        """Sans le poivre, le hash n'est pas reproductible : c'est exactement
        ce qui protege un dump de base."""
        settings.PASSWORD_HASH_PEPPER = _PEPPER
        with_pepper = hash_password("azerty123")

        settings.PASSWORD_HASH_PEPPER = "un-autre-poivre"
        assert hash_password("azerty123") != with_pepper

    @patch("app.pipeline.detect.masking.settings")
    def test_is_stable_for_correlation(self, settings):
        """Deux occurrences du meme mot de passe doivent partager le meme hash
        -- c'est le signal recherche (reutilisation)."""
        settings.PASSWORD_HASH_PEPPER = _PEPPER
        assert hash_password("azerty123") == hash_password("azerty123")

    @patch("app.pipeline.detect.masking.settings")
    def test_differs_for_different_passwords(self, settings):
        settings.PASSWORD_HASH_PEPPER = _PEPPER
        assert hash_password("azerty123") != hash_password("azerty124")

    @patch("app.pipeline.detect.masking.settings")
    def test_never_contains_the_plaintext(self, settings):
        settings.PASSWORD_HASH_PEPPER = _PEPPER
        assert "azerty123" not in hash_password("azerty123")

    @patch("app.pipeline.detect.masking.settings")
    def test_missing_pepper_fails_loudly(self, settings):
        """Echouer visiblement plutot que stocker avec une protection degradee
        que personne ne remarque."""
        settings.PASSWORD_HASH_PEPPER = ""
        with pytest.raises(ValueError, match="PASSWORD_HASH_PEPPER"):
            hash_password("azerty123")


class TestCredentialsUsesPasswordHash:
    @patch("app.pipeline.detect.masking.settings")
    def test_hash_is_of_the_password_only(self, settings):
        """Le hash porte le mot de passe seul, pas le couple entier : sinon
        deux comptes partageant un mot de passe seraient incomparables."""
        settings.PASSWORD_HASH_PEPPER = _PEPPER

        first = find_credentials("alice@example.com:motdepasse1")
        second = find_credentials("bob@example.com:motdepasse1")

        assert len(first) == 1 and len(second) == 1
        assert first[0].value_hash == second[0].value_hash

    @patch("app.pipeline.detect.masking.settings")
    def test_different_passwords_differ(self, settings):
        settings.PASSWORD_HASH_PEPPER = _PEPPER

        first = find_credentials("alice@example.com:motdepasse1")
        second = find_credentials("alice@example.com:motdepasse2")

        assert first[0].value_hash != second[0].value_hash

    @patch("app.pipeline.detect.masking.settings")
    def test_no_plaintext_leaks_into_the_match(self, settings):
        """Regle non negociable : ni le mot de passe ni l'email complet ne
        doivent apparaitre en clair dans ce qui sera persiste."""
        settings.PASSWORD_HASH_PEPPER = _PEPPER

        match = find_credentials("alice@example.com:SuperSecret42")[0]

        assert "SuperSecret42" not in match.value_masked
        assert "SuperSecret42" not in match.value_hash
        assert "alice@example.com" not in match.value_masked
