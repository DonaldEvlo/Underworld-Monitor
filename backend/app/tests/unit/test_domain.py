"""Tests du pattern domain (CONTRIBUTING.md §4 : tout detecteur DOIT avoir des tests).

L'enjeu principal couvert ici est la _TLD_ALLOWLIST : c'est elle qui decide si
une detection existe. Un TLD absent rend la chaine aval (matching, alerting)
integralement muette sur ce domaine, sans erreur ni log -- une panne
silencieuse. Les TLD africains/francophones sont donc verrouilles par test :
ils constituent le perimetre cible de la plateforme."""

from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.patterns.domain import find_domains


def _masked(text: str) -> set[str]:
    return {m.value_masked for m in find_domains(text)}


class TestClearnetDomains:
    def test_detects_simple_domain(self):
        assert _masked("visit example.com now") == {"example.com"}

    def test_detects_subdomain(self):
        assert _masked("mail.example.com leaked") == {"mail.example.com"}

    def test_is_case_insensitive(self):
        """Un domaine est insensible a la casse : EXAMPLE.COM == example.com."""
        assert _masked("EXAMPLE.COM") == {"example.com"}

    def test_clearnet_is_not_validated(self):
        """Un domaine clearnet n'est pas verifiable structurellement (contrairement
        a un .onion v3, dont la longueur base32 est contrainte)."""
        matches = find_domains("example.com")
        assert matches and all(m.validated is False for m in matches)

    def test_type_is_domain(self):
        matches = find_domains("example.com")
        assert matches and all(m.type == DetectionType.DOMAIN for m in matches)

    def test_deduplicates_repeated_domains(self):
        matches = find_domains("example.com and example.com again")
        assert len(matches) == 1


class TestTargetPerimeterTlds:
    """Non-regression du correctif : ces TLD manquaient, rendant la plateforme
    aveugle sur son propre cas d'usage (constate le 2026-08-17, 0 detection
    .sn en base alors qu'une entite operateur.sn etait surveillee)."""

    def test_detects_senegal_domain(self):
        assert _masked("dump from operateur.sn") == {"operateur.sn"}

    def test_detects_west_african_tlds(self):
        text = "targets: acme.ci, acme.ml, acme.bf, acme.tg, acme.ng"
        assert _masked(text) == {"acme.ci", "acme.ml", "acme.bf", "acme.tg", "acme.ng"}

    def test_detects_maghreb_tlds(self):
        assert _masked("acme.ma acme.dz acme.tn") == {"acme.ma", "acme.dz", "acme.tn"}

    def test_detects_central_and_southern_african_tlds(self):
        assert _masked("acme.cm acme.cd acme.za acme.ke") == {
            "acme.cm",
            "acme.cd",
            "acme.za",
            "acme.ke",
        }

    def test_subdomain_on_target_tld(self):
        """Cas reel attendu : un sous-domaine de l'entite surveillee."""
        assert _masked("webmail.operateur.sn credentials") == {"webmail.operateur.sn"}


class TestOnionDomains:
    _ONION = "a" * 56 + ".onion"

    def test_detects_onion_v3(self):
        matches = find_domains(f"mirror at {self._ONION}")
        assert [m.value_hash for m in matches] == [hash_value(self._ONION)]

    def test_onion_is_masked_unlike_clearnet(self):
        """Distinction assumee de mask_domain : un .onion est masque (adresse
        d'un service cache), un clearnet reste lisible pour l'analyste."""
        onion_masked = find_domains(self._ONION)[0].value_masked
        assert onion_masked != self._ONION
        assert onion_masked.endswith(".onion")
        assert find_domains("operateur.sn")[0].value_masked == "operateur.sn"

    def test_onion_is_validated(self):
        """La structure d'un .onion v3 est contrainte (56 caracteres base32),
        donc verifiable -- contrairement a un domaine clearnet."""
        matches = find_domains(self._ONION)
        assert matches and all(m.validated is True for m in matches)

    def test_onion_v2_is_ignored(self):
        """Le v2 (16 caracteres) est retire du reseau Tor."""
        assert _masked("a" * 16 + ".onion") == set()

    def test_onion_is_not_double_counted_as_clearnet(self):
        matches = find_domains(self._ONION)
        assert len(matches) == 1


class TestFalsePositives:
    """La liste blanche existe pour couper le bruit non-domaine du corpus
    (noms de fichiers, code source, ponctuation) -- voir docstring de domain.py."""

    def test_windows_filename_is_not_a_domain(self):
        assert _masked("C:\\Windows\\Pagefile.sys") == set()

    def test_source_code_call_is_not_a_domain(self):
        assert _masked("arrayList.add(item)") == set()

    def test_unknown_tld_is_ignored(self):
        assert _masked("archive.zzzz") == set()

    def test_sentence_punctuation_is_not_a_domain(self):
        assert _masked("Download it.Add torrent to client") == set()


class TestNoRawValueLeak:
    """CONTRIBUTING.md regle 2 : jamais de PII brute. Un domaine reste lisible en clair
    par decision documentee (indicateur, pas PII), mais le hash doit rester
    non reversible et coherent pour la correlation."""

    def test_hash_matches_normalized_lowercase_value(self):
        matches = find_domains("EXAMPLE.COM")
        assert matches[0].value_hash == hash_value("example.com")

    def test_hash_is_stable_across_casing(self):
        assert (
            find_domains("Example.Com")[0].value_hash
            == find_domains("example.com")[0].value_hash
        )
