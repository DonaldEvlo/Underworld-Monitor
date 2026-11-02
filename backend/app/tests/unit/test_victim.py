from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.patterns.victim import find_victims


class TestFindVictims:
    def test_extracts_declared_victim_name(self):
        text = "Victime: Exemple Apparatebau AG\nDate: 2026-08-10\n\nPharma Test is a manufacturer."
        matches = find_victims(text)
        assert [m.value_masked for m in matches] == ["Exemple Apparatebau AG"]

    def test_extracts_aggregator_victim_marker(self):
        """Les agregateurs multi-groupes utilisent "Victime annoncee:" la ou un
        leak site pose "Victime:" (voir collect/ransomlook/adapter.py)."""
        text = "Groupe: LockBit\nVictime annoncee: Acme Corp\nDecouvert le: 2026-08-10"
        assert [m.value_masked for m in find_victims(text)] == ["Acme Corp"]

    def test_result_is_organization_and_validated(self):
        """`validated=True` distingue une victime declaree par la source d'une
        organisation inferee par le NER (voir patterns/organization.py)."""
        matches = find_victims(
            "Victime: Exemple Mechanical Contractors\nDate: 2026-08-10"
        )
        assert matches
        for match in matches:
            assert match.type == DetectionType.ORGANIZATION
            assert match.validated is True

    def test_text_without_marker_returns_nothing(self):
        text = "Une annonce quelconque qui mentionne Siemens sans marqueur structure."
        assert find_victims(text) == []

    def test_empty_text_returns_nothing(self):
        assert find_victims("") == []

    def test_marker_must_start_a_line(self):
        """Le marqueur n'est reconnu qu'en debut de ligne : une occurrence citee
        au fil d'une description ne doit pas produire de fausse victime."""
        text = "La page indique Victime: quelque chose au milieu d'une phrase."
        assert find_victims(text) == []

    def test_multiple_announcements_yield_multiple_victims(self):
        text = "Victime: Alpha Industries\nDate: 2026-08-01\n\nVictime: Beta Corp\nDate: 2026-08-02"
        assert [m.value_masked for m in find_victims(text)] == [
            "Alpha Industries",
            "Beta Corp",
        ]

    def test_same_victim_repeated_is_deduplicated_case_insensitively(self):
        text = "Victime: Alpha Industries\n\nVictime: ALPHA INDUSTRIES\n"
        matches = find_victims(text)
        assert len(matches) == 1

    def test_value_hash_is_derived_from_the_case_normalized_name(self):
        """Deux graphies du meme nom, vues sur des annonces differentes, doivent
        partager le meme hash pour se regrouper (voir
        DetectionRepository.top_organization_candidates)."""
        upper = find_victims("Victime: ALPHA INDUSTRIES")
        title = find_victims("Victime: Alpha Industries")
        assert upper[0].value_hash == title[0].value_hash
        assert upper[0].value_hash == hash_value("alpha industries")

    def test_surrounding_whitespace_is_normalized(self):
        matches = find_victims("Victime:   Alpha   Industries  \nDate: 2026-08-01")
        assert matches[0].value_masked == "Alpha Industries"

    def test_trivial_name_is_ignored(self):
        assert find_victims("Victime: AB") == []
