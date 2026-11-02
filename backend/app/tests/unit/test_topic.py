from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.patterns.topic import find_source_topics


class TestFindSourceTopics:
    def test_extracts_section_marker(self):
        text = "Titre\nSection: СМИ / NEWS\n\nCorps de l'annonce."
        assert [m.value_masked for m in find_source_topics(text)] == ["СМИ / NEWS"]

    def test_extracts_forum_marker(self):
        text = "Titre\nForum: CARDING\n\nCorps du post."
        assert [m.value_masked for m in find_source_topics(text)] == ["CARDING"]

    def test_result_is_source_topic_and_validated(self):
        """Lu la ou la source l'a mis : ce n'est pas une inference."""
        matches = find_source_topics("Forum: Hacking")
        assert matches
        for match in matches:
            assert match.type == DetectionType.SOURCE_TOPIC
            assert match.validated is True

    def test_marker_must_start_a_line(self):
        text = "Le post precise Forum: quelque chose au milieu d'une phrase."
        assert find_source_topics(text) == []

    def test_text_without_marker_returns_nothing(self):
        assert find_source_topics("Un post sans aucun classement declare.") == []

    def test_empty_text_returns_nothing(self):
        assert find_source_topics("") == []

    def test_same_topic_repeated_is_deduplicated(self):
        text = "Forum: CARDING\n\nForum: carding\n"
        assert len(find_source_topics(text)) == 1

    def test_cyrillic_topic_is_deduplicated_case_insensitively(self):
        """casefold gere les alphabets non latins (constate en base : la
        section XSSF est en cyrillique)."""
        text = "Section: СМИ\n\nSection: сми\n"
        assert len(find_source_topics(text)) == 1

    def test_value_hash_is_derived_from_the_casefolded_label(self):
        matches = find_source_topics("Forum: CARDING")
        assert matches[0].value_hash == hash_value("carding")

    def test_surrounding_whitespace_is_normalized(self):
        matches = find_source_topics("Forum:   Website   Hacking  ")
        assert matches[0].value_masked == "Website Hacking"

    def test_overlong_label_is_ignored(self):
        """Garde-fou : un libelle tres long n'est plus une rubrique mais une
        phrase happee par le marqueur."""
        assert find_source_topics("Forum: " + "x" * 200) == []

    def test_trivial_label_is_ignored(self):
        assert find_source_topics("Forum: -") == []
