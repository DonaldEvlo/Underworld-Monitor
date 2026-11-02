"""Tests du masquage (voir pipeline/detect/masking.py).

Ce module porte la regle non negociable du projet (CONTRIBUTING.md §2) : aucune PII
brute ne doit sortir de la couche detect. Tout ce qui est persiste, affiche ou
envoye a un LLM passe par ici -- une regression a cet endroit exposerait des
donnees reelles de victimes, sans qu'aucun autre test ne s'en apercoive.

D'ou l'insistance des tests ci-dessous sur une propriete unique : la valeur
d'origine ne doit jamais etre reconstituable depuis la sortie."""

from app.pipeline.detect.masking import (
    hash_value,
    mask_card,
    mask_domain,
    mask_email,
    mask_generic,
    mask_iban,
)


class TestHashValue:
    def test_is_deterministic(self):
        """La correlation entre detections repose entierement sur cette
        propriete : deux occurrences de la meme valeur doivent partager leur
        hash (voir DetectionRepository.top_organization_candidates)."""
        assert hash_value("valeur") == hash_value("valeur")

    def test_differs_for_different_values(self):
        assert hash_value("a@example.com") != hash_value("b@example.com")

    def test_is_sha256_hex(self):
        digest = hash_value("valeur")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_does_not_contain_the_plaintext(self):
        """Un hash n'est pas reversible : c'est ce qui permet de correler sans
        reexposer la valeur."""
        assert "supersecret" not in hash_value("supersecret")

    def test_is_case_sensitive(self):
        """hash_value ne normalise rien -- c'est a l'appelant de le faire
        (voir patterns/organization.py qui hashe la forme minuscule)."""
        assert hash_value("Valeur") != hash_value("valeur")


class TestMaskEmail:
    def test_keeps_first_char_and_domain(self):
        assert mask_email("jean.dupont@exemple.com") == "j***@exemple.com"

    def test_hides_the_local_part(self):
        """Le domaine reste lisible (utile a l'analyste pour rattacher a une
        entite), la partie locale identifie la personne : elle disparait."""
        masked = mask_email("jean.dupont@exemple.com")
        assert "dupont" not in masked
        assert "jean." not in masked

    def test_distinguishes_two_different_emails(self):
        assert mask_email("alice@exemple.com") != mask_email("bob@exemple.com")

    def test_handles_empty_local_part(self):
        assert mask_email("@exemple.com") == "***@exemple.com"

    def test_falls_back_to_generic_without_at_sign(self):
        """Une chaine sans "@" n'est pas un email : plutot que de la laisser en
        clair, elle passe par le masquage generique."""
        assert mask_email("pasunemail") == mask_generic("pasunemail")


class TestMaskCard:
    def test_keeps_first_and_last_digits_only(self):
        assert mask_card("4111111111111111") == "4***-****-****-1111"

    def test_never_exposes_the_full_pan(self):
        """Le PAN complet ne doit jamais apparaitre : c'est la donnee la plus
        sensible du corpus."""
        masked = mask_card("4242424242424242")
        assert "4242424242424242" not in masked
        assert masked.count("*") >= 8

    def test_strips_separators_before_masking(self):
        assert mask_card("4111-1111-1111-1111") == "4***-****-****-1111"
        assert mask_card("4111 1111 1111 1111") == "4***-****-****-1111"

    def test_falls_back_to_generic_when_too_short(self):
        assert mask_card("4111") == mask_generic("4111")


class TestMaskIban:
    def test_keeps_country_code_and_last_four(self):
        masked = mask_iban("GB82WEST12345698765432")
        assert masked.startswith("GB")
        assert masked.endswith("5432")

    def test_hides_the_account_number(self):
        masked = mask_iban("GB82WEST12345698765432")
        assert "WEST123456" not in masked

    def test_strips_spaces_before_masking(self):
        assert mask_iban("GB82 WEST 1234 5698 7654 32") == mask_iban(
            "GB82WEST12345698765432"
        )

    def test_falls_back_to_generic_when_too_short(self):
        assert mask_iban("GB82") == mask_generic("GB82")


class TestMaskGeneric:
    def test_keeps_two_chars_at_each_end(self):
        assert mask_generic("abcdefghij") == "ab******ij"

    def test_fully_masks_short_values(self):
        """Sous 7 caracteres, garder 4 caracteres sur 6 ne masquerait presque
        rien : la valeur est entierement remplacee."""
        assert mask_generic("abcdef") == "******"
        assert mask_generic("ab") == "**"

    def test_preserves_length(self):
        """La longueur reste visible (utile pour distinguer deux secrets) sans
        rien reveler du contenu."""
        for value in ["abcdefghij", "abcdef", "a" * 40]:
            assert len(mask_generic(value)) == len(value)

    def test_handles_empty_string(self):
        assert mask_generic("") == ""


class TestMaskDomain:
    def test_clearnet_domain_stays_readable(self):
        """Un domaine n'est pas une PII (voir patterns/domain.py) : le masquer
        rendrait la detection inutilisable sans proteger personne."""
        assert mask_domain("exemple.com") == "exemple.com"
        assert mask_domain("ibb.co") == "ibb.co"

    def test_onion_address_is_partially_masked(self):
        """56 caracteres illisibles de toute facon : on garde de quoi
        distinguer deux adresses sans encombrer l'affichage."""
        onion = "a" * 52 + "bcde" + ".onion"
        masked = mask_domain(onion)
        assert masked.endswith(".onion")
        assert "..." in masked
        assert len(masked) < len(onion)
