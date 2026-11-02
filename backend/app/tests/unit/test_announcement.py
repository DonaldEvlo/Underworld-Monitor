from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.patterns.announcement import find_announcements


class TestFindAnnouncements:
    def test_detects_database_leak(self):
        text = "Titre: pintando.com.mx database 2025-2026 breached\n\nCorps."
        assert [m.value_masked for m in find_announcements(text)] == ["database_leak"]

    def test_detects_stealer_logs(self):
        text = "Titre: VIP ULP 7.03.2026 - @updh1 11GB"
        assert [m.value_masked for m in find_announcements(text)] == ["stealer_logs"]

    def test_detects_combolist(self):
        text = "Titre: ✪ [17k+] Combo ✪ { Sri Lanka } ✪ FRESH & HQ ✪"
        assert [m.value_masked for m in find_announcements(text)] == ["combolist"]

    def test_detects_generic_breach(self):
        text = "Titre: ExempleNYC - Leaked, Download!"
        assert [m.value_masked for m in find_announcements(text)] == ["breach"]

    def test_result_is_announcement_and_validated(self):
        matches = find_announcements("Titre: Telekom Serbia - DB 650k+ Lines")
        assert matches
        for match in matches:
            assert match.type == DetectionType.ANNOUNCEMENT
            assert match.validated is True

    def test_stealer_logs_wins_over_generic_breach(self):
        """Ordre des categories : la plus specifique gagne. Un titre qui
        contient a la fois "ULP" et "leaked" decrit des logs de stealer."""
        text = "Titre: ULP LOGS leaked 196GB"
        assert [m.value_masked for m in find_announcements(text)] == ["stealer_logs"]

    def test_title_without_keyword_is_not_categorized(self):
        """Mieux vaut ne rien dire que de qualifier a tort."""
        assert find_announcements("Titre: Questions and Discussion") == []

    def test_keywords_are_matched_on_word_boundaries(self):
        """ "db" ne doit pas matcher dans "dbeaver", "logs" pas dans "blogs"."""
        assert find_announcements("Titre: dbeaver tutorial for blogs") == []

    def test_marker_must_start_a_line(self):
        text = "Le post indique Titre: something database au milieu."
        assert find_announcements(text) == []

    def test_text_without_marker_returns_nothing(self):
        assert find_announcements("Un contenu sans titre structure.") == []

    def test_empty_text_returns_nothing(self):
        assert find_announcements("") == []

    def test_same_category_twice_is_deduplicated(self):
        text = "Titre: Alpha database leaked\n\nTitre: Beta database dump\n"
        assert len(find_announcements(text)) == 1

    def test_value_hash_is_derived_from_the_category(self):
        matches = find_announcements("Titre: Something breached")
        assert matches[0].value_hash == hash_value("breach")
