"""Tests des validateurs checksum (voir pipeline/detect/validators.py).

Ces validateurs sont ce qui distingue une vraie carte/IBAN d'une suite de
chiffres au hasard : sans eux, le pattern regex seul remonterait des numeros de
commande et des identifiants concatenes comme des donnees bancaires fuitees.
Ils conditionnent directement `DetectionContract.validated`, donc la severite
de l'alerte (voir pipeline/alerting/rules.py) -- un faux positif ici remonte jusqu'a
l'analyste.

Les numeros utilises sont des valeurs de TEST publiques (documentation des
reseaux de paiement, exemples ISO 13616), jamais des donnees reelles."""

from app.pipeline.detect.validators import iban_is_valid, luhn_is_valid


class TestLuhnIsValid:
    def test_accepts_known_valid_test_numbers(self):
        # Numeros de test publies par les reseaux (Visa, Mastercard, Amex,
        # Discover) -- jamais rattaches a un compte reel.
        for number in [
            "4111111111111111",
            "5500000000000004",
            "340000000000009",
            "6011000000000004",
            "4242424242424242",
        ]:
            assert luhn_is_valid(number) is True, number

    def test_rejects_number_with_wrong_checksum(self):
        """Un seul chiffre modifie sur un numero valide doit suffire a le
        rejeter -- c'est exactement ce que Luhn detecte."""
        assert luhn_is_valid("4111111111111111") is True
        assert luhn_is_valid("4111111111111112") is False

    def test_rejects_transposed_digits(self):
        """Luhn detecte la plupart des inversions de deux chiffres adjacents,
        l'erreur de saisie la plus courante apres la faute de frappe."""
        assert luhn_is_valid("4111111111111111") is True
        assert luhn_is_valid("1411111111111111") is False

    def test_rejects_repeated_digits(self):
        assert luhn_is_valid("1111111111111111") is False
        assert luhn_is_valid("0000000000000001") is False

    def test_rejects_non_digit_input(self):
        """`digits` est cense arriver deja nettoye (voir patterns/card.py) :
        une entree non numerique est une erreur d'appel, elle doit etre rejetee
        sans lever."""
        assert luhn_is_valid("4111-1111-1111-1111") is False
        assert luhn_is_valid("4111 1111 1111 1111") is False
        assert luhn_is_valid("abcd") is False
        assert luhn_is_valid("") is False

    def test_all_zeros_passes_checksum_but_is_not_a_real_card(self):
        """Documente une limite connue : "0000000000000000" satisfait Luhn
        (total = 0, divisible par 10). Le validateur ne ment pas -- c'est au
        pattern de ne pas remonter ce genre de sequence."""
        assert luhn_is_valid("0000000000000000") is True


class TestIbanIsValid:
    def test_accepts_known_valid_test_ibans(self):
        # Exemples publics de la norme ISO 13616 / documentation bancaire.
        for iban in [
            "GB82WEST12345698765432",
            "DE89370400440532013000",
            "FR1420041010050500013M02606",
            "BE68539007547034",
        ]:
            assert iban_is_valid(iban) is True, iban

    def test_rejects_wrong_check_digits(self):
        """Les deux chiffres de controle (positions 3-4) sont precisement ce
        que mod-97 verifie."""
        assert iban_is_valid("GB82WEST12345698765432") is True
        assert iban_is_valid("GB83WEST12345698765432") is False

    def test_rejects_altered_account_number(self):
        assert iban_is_valid("DE89370400440532013000") is True
        assert iban_is_valid("DE89370400440532013001") is False

    def test_rejects_malformed_structure(self):
        """Un IBAN commence toujours par 2 lettres de pays puis 2 chiffres de
        controle -- toute autre forme est rejetee avant meme le calcul."""
        assert iban_is_valid("1B82WEST12345698765432") is False  # pays non alpha
        assert iban_is_valid("GBX2WEST12345698765432") is False  # cle non numerique
        assert iban_is_valid("GB82") is False  # trop court
        assert iban_is_valid("") is False

    def test_rejects_unformatted_input(self):
        """`iban` est cense arriver nettoye (majuscules, sans espaces, voir
        patterns/iban.py) : les separateurs doivent etre rejetes plutot que
        silencieusement ignores."""
        assert iban_is_valid("GB82 WEST 1234 5698 7654 32") is False
        assert iban_is_valid("gb82west12345698765432") is False

    def test_does_not_raise_on_unexpected_characters(self):
        """Robustesse : le corpus reel contient des chaines arbitraires, le
        validateur ne doit jamais lever."""
        for value in ["GB82WEST!!!!5698765432", "XX00" + "€" * 12, "GB82\n\tWEST"]:
            assert iban_is_valid(value) is False
