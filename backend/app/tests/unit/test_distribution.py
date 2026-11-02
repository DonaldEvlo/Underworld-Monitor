from app.contracts.detection import DetectionType
from app.pipeline.detect.masking import hash_value
from app.pipeline.detect.patterns.distribution import find_distribution_channels


class TestFindDistributionChannels:
    def test_detects_known_file_host(self):
        matches = find_distribution_channels(["https://files.catbox.moe/ab12cd.zip"])
        assert [m.value_masked for m in matches] == ["files.catbox.moe"]

    def test_result_is_distribution_channel_and_validated(self):
        """Appartenance a une liste connue d'hebergeurs : pas une inference."""
        matches = find_distribution_channels(["https://mega.nz/file/gRsAkQgA"])
        assert matches
        for match in matches:
            assert match.type == DetectionType.DISTRIBUTION_CHANNEL
            assert match.validated is True

    def test_detects_paste_and_messaging_hosts(self):
        urls = ["https://t.me/somechannel", "https://rentry.co/abcd"]
        found = {m.value_masked for m in find_distribution_channels(urls)}
        assert found == {"t.me", "rentry.co"}

    def test_unknown_hosts_are_ignored(self):
        """Sur un corpus de forums, la majorite des liens sortants sont du bruit
        (reseaux sociaux, pages d'accueil) -- seuls les hebergeurs comptent."""
        urls = [
            "https://www.instagram.com/someone",
            "https://www.roblox.com/games/123",
            "https://accounts.google.com/signin",
        ]
        assert find_distribution_channels(urls) == []

    def test_subdomain_of_known_host_is_detected(self):
        """Un hebergeur doit etre reconnu quel que soit son sous-domaine."""
        matches = find_distribution_channels(["https://eu2.pixeldrain.com/u/xyz"])
        assert [m.value_masked for m in matches] == ["eu2.pixeldrain.com"]

    def test_lookalike_domain_is_not_matched_by_substring(self):
        """Comparaison par labels, jamais par sous-chaine (CONTRIBUTING.md §8) :
        "mega.nz.evil.com" n'est pas mega.nz."""
        assert find_distribution_channels(["https://mega.nz.evil.com/x"]) == []
        assert find_distribution_channels(["https://notmega.nz/x"]) == []

    def test_only_the_host_is_kept_never_the_path(self):
        """Le chemin d'une URL de fuite designe frequemment la victime
        (constate en base : doxbin.net/upload/<nom>) -- ce serait de la PII."""
        matches = find_distribution_channels(
            ["https://doxbin.net/upload/FlavioNantesBolsonaro"]
        )
        assert matches[0].value_masked == "doxbin.net"
        assert "Flavio" not in matches[0].value_masked

    def test_www_prefix_is_normalized(self):
        matches = find_distribution_channels(["https://www.mediafire.com/file/x"])
        assert matches[0].value_masked == "mediafire.com"

    def test_same_host_twice_is_deduplicated(self):
        urls = ["https://t.me/a", "https://t.me/b"]
        assert len(find_distribution_channels(urls)) == 1

    def test_empty_and_malformed_input_is_safe(self):
        assert find_distribution_channels([]) == []
        assert find_distribution_channels(["", "not-an-url", "://broken"]) == []

    def test_value_hash_is_derived_from_the_host(self):
        matches = find_distribution_channels(["https://gofile.io/d/abc"])
        assert matches[0].value_hash == hash_value("gofile.io")
