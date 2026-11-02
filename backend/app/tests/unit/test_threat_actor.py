from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.patterns.threat_actor import find_threat_actors


class TestFindThreatActors:
    def test_extracts_declared_group(self):
        text = "Groupe: LockBit\nVictime annoncee: Acme Corp\nDecouvert le: 2026-08-10"
        assert [m.value_masked for m in find_threat_actors(text)] == ["LockBit"]

    def test_result_is_threat_actor_and_validated(self):
        """`validated` porte sur "la source declare bien ce groupe", jamais sur
        une attribution verifiee (voir docstring du module)."""
        matches = find_threat_actors("Groupe: Akira")
        assert matches
        for match in matches:
            assert match.type == DetectionType.THREAT_ACTOR
            assert match.validated is True

    def test_short_group_names_are_accepted(self):
        """Certains noms de gangs sont tres courts ("3AM", "8base")."""
        assert [m.value_masked for m in find_threat_actors("Groupe: 3AM")] == ["3AM"]

    def test_marker_must_start_a_line(self):
        text = "Le post mentionne Groupe: quelque chose au milieu."
        assert find_threat_actors(text) == []

    def test_text_without_marker_returns_nothing(self):
        assert find_threat_actors("Une annonce sans groupe declare.") == []

    def test_empty_text_returns_nothing(self):
        assert find_threat_actors("") == []

    def test_same_group_repeated_is_deduplicated_case_insensitively(self):
        text = "Groupe: LockBit\n\nGroupe: lockbit\n"
        assert len(find_threat_actors(text)) == 1

    def test_multiple_groups_yield_multiple_actors(self):
        text = "Groupe: LockBit\n\nGroupe: BlackCat\n"
        assert [m.value_masked for m in find_threat_actors(text)] == [
            "LockBit",
            "BlackCat",
        ]

    def test_value_hash_is_derived_from_the_casefolded_name(self):
        matches = find_threat_actors("Groupe: LockBit")
        assert matches[0].value_hash == hash_value("lockbit")

    def test_surrounding_whitespace_is_normalized(self):
        matches = find_threat_actors("Groupe:   Black   Basta  ")
        assert matches[0].value_masked == "Black Basta"

    def test_trivial_and_overlong_names_are_ignored(self):
        assert find_threat_actors("Groupe: -") == []
        assert find_threat_actors("Groupe: " + "x" * 200) == []
