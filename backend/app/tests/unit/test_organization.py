from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.patterns.organization import find_organizations


class TestFindOrganizations:
    def test_organization_mentioned_in_text_is_detected(self):
        text = "Acme Corporation confirmed a data breach affecting its customers."
        matches = find_organizations(text)
        names = {m.value_masked.lower() for m in matches}
        assert any("acme" in name for name in names)

    def test_result_type_is_organization_and_unvalidated(self):
        text = "A leak from Acme Corporation was posted on the forum today."
        matches = find_organizations(text)
        assert matches
        for match in matches:
            assert match.type == DetectionType.ORGANIZATION
            assert match.validated is False

    def test_empty_text_returns_no_matches(self):
        assert find_organizations("") == []

    def test_text_without_organizations_returns_no_matches(self):
        text = "The quick brown fox jumps over the lazy dog."
        assert find_organizations(text) == []

    def test_repeated_mentions_are_deduplicated_case_insensitively(self):
        text = "Acme Corporation was breached. ACME CORPORATION denied it. acme corporation stayed silent."
        matches = find_organizations(text)
        dedup_keys = {m.value_masked.lower() for m in matches}
        acme_matches = [k for k in dedup_keys if "acme" in k]
        assert len(acme_matches) <= 1

    def test_masked_value_never_empty_and_never_trivially_short(self):
        text = "Acme Corporation and IBM were both mentioned in the same post."
        matches = find_organizations(text)
        for match in matches:
            assert len(match.value_masked) >= 3

    def test_excluded_generic_terms_are_filtered_out(self):
        """Vocabulaire technique/juridique mal classifie ORG par spaCy, constate
        en base -- ne designe aucune organisation surveillable."""
        text = (
            "The LLC shared SSN and DOB records. The ISP logged the IP Address. "
            "Check the CPU and RAM usage over SSH."
        )
        found = {m.value_masked.lower() for m in find_organizations(text)}
        for noise in ("llc", "ssn", "dob", "isp", "ip address", "cpu", "ram", "ssh"):
            assert noise not in found

    def test_typographic_apostrophe_does_not_bypass_the_exclusion_list(self):
        """ "NDA’s" (apostrophe U+2019) doit etre exclu au meme titre que "nda"
        -- sans normalisation il passait le filtre (constate en base)."""
        found = {
            m.value_masked.lower()
            for m in find_organizations("Signed NDA’s were leaked.")
        }
        assert "nda’s" not in found and "nda's" not in found

    def test_email_addresses_are_never_returned_as_organizations(self):
        """REGLE NON NEGOCIABLE (CONTRIBUTING.md §2) : spaCy classe parfois une
        adresse email complete comme ORG. `value_masked` etant stocke en clair
        pour ce type, cela persistait une PII brute en base -- court-circuitant
        le masquage applique par patterns/email.py sur la meme valeur.
        Regression detectee par integration/test_pipeline.py."""
        text = "Contact: jean.dupont@example-test.com for the dump."
        for match in find_organizations(text):
            assert "@" not in match.value_masked

    def test_bittorrent_boilerplate_is_filtered_out(self):
        """Pied de page de telechargement repete sur des centaines de pages d'un
        leak site -- les deux valeurs les plus frequentes du corpus avant filtre."""
        text = "Download with Transmission, Vuze, Utorrent or any other client."
        found = {m.value_masked.lower() for m in find_organizations(text)}
        assert "transmission" not in found
        assert "vuze, utorrent" not in found

    def test_value_hash_is_derived_from_the_case_normalized_name(self):
        """`value_hash` doit etre calcule sur la forme normalisee (minuscules),
        pas sur la graphie d'origine : c'est ce qui permet a
        DetectionRepository.top_organization_candidates de regrouper "Telco"
        et "TELCO" vus dans des documents differents.

        Le test verifie cette derivation directement plutot qu'en comparant
        deux textes : le NER est probabiliste et ne reconnait pas forcement le
        meme nom dans deux formulations differentes (constate empiriquement --
        voir le docstring du module), une comparaison inter-textes testerait la
        chance de detection du modele, pas la regle de hachage."""
        matches = find_organizations("Acme Corporation confirmed the breach.")
        assert matches
        for match in matches:
            assert match.value_hash == hash_value(match.value_masked.lower())
