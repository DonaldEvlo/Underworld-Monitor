"""Tests du profil TTP par GANG (ransomware.live /v2/group/<gang>).

⚠️ Le point verrouille ici n'est pas le parsing mais la SEMANTIQUE : ces
techniques decrivent le mode operatoire d'un groupe, jamais l'incident d'une
victime donnee."""

from __future__ import annotations

from app.pipeline.enrich.ransomware_live import (
    GangProfile,
    group_profile_url,
    parse_group_profile,
)

# Extrait REEL du payload de `nightspire` (2026-09-15).
PAYLOAD_NIGHTSPIRE = {
    "name": "nightspire",
    "description": "NightSpire is a ransomware group that first emerged in March 2025.",
    "tools": ["Rclone"],
    "ttps": [
        {
            "tactic_id": "TA0001",
            "tactic_name": "Initial Access",
            "techniques": [
                {
                    "technique_id": "T1078",
                    "technique_name": "Valid Accounts",
                    "technique_details": "Compromised RDP credentials used for initial access.",
                },
                {
                    "technique_id": "T1190",
                    "technique_name": "Exploit Public-Facing Application",
                    "technique_details": (
                        "Exploitation of CVE-2024-55591 — FortiOS/FortiProxy "
                        "authentication bypass."
                    ),
                },
            ],
        }
    ],
}


class TestUrl:
    def test_endpoint_profil_distinct_des_victimes(self):
        """⚠️ `/v2/group/` (profil) et `/v2/groupvictims/` (victimes) repondent
        a deux questions differentes -- le premier avait ete classe inutile."""
        assert group_profile_url("NightSpire") == (
            "https://api.ransomware.live/v2/group/nightspire"
        )


class TestParsing:
    def test_techniques_aplaties_avec_leur_tactique(self):
        p = parse_group_profile("nightspire", PAYLOAD_NIGHTSPIRE)
        assert len(p.techniques) == 2
        assert {t.technique_id for t in p.techniques} == {"T1078", "T1190"}
        assert p.techniques[0].tactic_name == "Initial Access"

    def test_cve_extraite_du_texte_libre_des_details(self):
        """Les CVE ne sont dans AUCUN champ dedie : elles sont noyees dans
        `technique_details`. C'est le seul endroit du payload qui en porte."""
        p = parse_group_profile("nightspire", PAYLOAD_NIGHTSPIRE)
        assert p.cves == ("CVE-2024-55591",)

    def test_outils(self):
        assert parse_group_profile("nightspire", PAYLOAD_NIGHTSPIRE).tools == (
            "Rclone",
        )


class TestProfilVide:
    """Un profil vide se lit « non documente », jamais « pas de methode ».
    Mesure : 335 des 396 groupes n'ont aucun TTP, dont APT73 et KRYBIT qui
    portent 15 de nos 31 alertes."""

    def test_gang_sans_ttp(self):
        p = parse_group_profile(
            "krybit", {"name": "krybit", "ttps": None, "tools": None}
        )
        assert p.is_empty
        assert p.cves == ()

    def test_payload_inattendu_ne_leve_pas(self):
        for mauvais in (None, [], "erreur", {"message": "1 per 1 minute"}):
            p = parse_group_profile("x", mauvais)
            assert isinstance(p, GangProfile)
            assert p.is_empty

    def test_technique_sans_identifiant_ignoree(self):
        payload = {
            "ttps": [
                {
                    "tactic_id": "TA0001",
                    "tactic_name": "Initial Access",
                    "techniques": [{"technique_name": "Sans id"}, "pas un dict"],
                }
            ]
        }
        assert parse_group_profile("x", payload).techniques == ()


class TestReponseDuProfil:
    """⚠️ La limite de debit arrive en HTTP 200 avec un objet : elle ne doit
    jamais etre prise (et mise en cache) pour un profil vide."""

    def test_limite_de_debit_est_une_indisponibilite(self):
        from app.pipeline.enrich.ransomware_live import profile_payload

        assert profile_payload({"message": "1 per 1 minute"}) is None

    def test_formes_inattendues(self):
        from app.pipeline.enrich.ransomware_live import profile_payload

        for mauvais in (None, [], [{"ttps": []}], "texte", {}):
            assert profile_payload(mauvais) is None

    def test_profil(self):
        from app.pipeline.enrich.ransomware_live import profile_payload

        profil = {"name": "lockbit3", "ttps": []}
        assert profile_payload(profil) == [profil]


class TestOutilsParCategorie:
    """⚠️ Forme REELLE observee le 2026-09-30 sur lockbit3 : une liste contenant
    un dictionnaire categorie -> noms. La premiere version n'acceptait que des
    chaines, jetait tout en silence et declarait le gang « non documente »."""

    PAYLOAD_REEL = {
        "name": "lockbit3",
        "ttps": [],
        "tools": [
            {
                "CredentialTheft": ["Mimikatz", "LaZagne"],
                "Exfiltration": ["RClone", "MEGA", "File[.]io"],
                "RMM-Tools": ["AnyDesk"],
            }
        ],
    }

    def test_forme_reelle_categories_conservees(self):
        p = parse_group_profile("lockbit3", self.PAYLOAD_REEL)
        assert not p.is_empty
        assert dict(p.tool_groups)["Exfiltration"] == ("RClone", "MEGA", "File[.]io")
        assert "Mimikatz" in p.tools
        assert len(p.tools) == 6

    def test_ancienne_forme_liste_de_chaines(self):
        p = parse_group_profile("x", {"tools": ["Cobalt Strike", "Cobalt Strike"]})
        assert p.tool_groups == (("", ("Cobalt Strike",)),)
        assert p.tools == ("Cobalt Strike",)

    def test_dictionnaire_direct_et_valeurs_hostiles(self):
        p = parse_group_profile(
            "x", {"tools": {"Offsec": ["Metasploit", None, {"x": 1}, ""]}}
        )
        assert p.tool_groups == (("Offsec", ("Metasploit",)),)
