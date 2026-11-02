"""Extraction de TTP declares (CVE + techniques MITRE) -- pur, sans reseau."""

from app.pipeline.enrich.ttp import extract_cves, extract_declared_techniques


class TestCve:
    def test_extracts_and_normalises(self):
        txt = "Exploited cve-2025-61882 and CVE-2026-20045, again CVE-2025-61882."
        assert extract_cves(txt) == ["CVE-2025-61882", "CVE-2026-20045"]

    def test_ignores_malformed(self):
        assert extract_cves("CVE-25-1 or CVE-2025 or nothing") == []

    def test_empty(self):
        assert extract_cves("") == []
        assert extract_cves(None) == []


class TestTechniques:
    def test_named_techniques_map_to_mitre(self):
        txt = "Initial access via spear-phishing, then RDP and mimikatz."
        ids = {t.technique_id for t in extract_declared_techniques(txt)}
        assert {"T1566", "T1021.001", "T1003"} <= ids

    def test_one_entry_per_technique(self):
        txt = "phishing phishing phishing"
        techs = extract_declared_techniques(txt)
        assert [t.technique_id for t in techs] == ["T1566"]

    def test_bare_exploit_is_not_matched(self):
        """« exploit » seul est trop bruite (321 docs) : non retenu."""
        assert extract_declared_techniques("exploit kit for sale") == []

    def test_public_facing_exploit_is_matched(self):
        techs = extract_declared_techniques("exploited a public-facing application")
        assert [t.technique_id for t in techs] == ["T1190"]

    def test_empty(self):
        assert extract_declared_techniques(None) == []


class TestLiensDeReference:
    """Les identifiants viennent d'un tiers et finissent dans un `href`."""

    def test_technique_et_sous_technique(self):
        from app.pipeline.enrich.ttp import mitre_technique_url

        assert mitre_technique_url("T1190") == (
            "https://attack.mitre.org/techniques/T1190/"
        )
        assert mitre_technique_url("t1059.001") == (
            "https://attack.mitre.org/techniques/T1059/001/"
        )

    def test_forme_inattendue_aucun_lien(self):
        from app.pipeline.enrich.ttp import cve_url, mitre_technique_url

        for hostile in ("javascript:alert(1)", "T1190/../../x", "", None, "TA0001"):
            assert mitre_technique_url(hostile) is None
        for hostile in ("CVE-2023", "javascript:x", "CVE-2023-4966<script>", None):
            assert cve_url(hostile) is None

    def test_cve(self):
        from app.pipeline.enrich.ttp import cve_url

        assert cve_url("cve-2023-4966") == (
            "https://nvd.nist.gov/vuln/detail/CVE-2023-4966"
        )
