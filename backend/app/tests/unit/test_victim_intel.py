"""Tests des renseignements par victime (ransomware.live).

⚠️ Le test le plus important est `TestAucunePII` : il verrouille la frontiere
de la regle 2. Si un jour l'amont ajoute un champ portant un identifiant, ces
tests doivent etre relus AVANT d'elargir le parsing."""

from __future__ import annotations

from dataclasses import fields

from app.pipeline.enrich.ransomware_live import VictimIntel, parse_victim_intel

# Extrait REEL du payload `/v2/groupvictims/lockbit3` (2026-09-15).
PAYLOAD = [
    {
        "victim": "Assih",
        "domain": "assurance-exemple.com",
        "attackdate": "2026-09-02T00:00:00+00:00",
        "country": "FR",
        "activity": "Healthcare",
        "data_size": "240GB",
        "infostealer": {
            "employees": 3,
            "employees_url": 3,
            "users": 11,
            "users_url": 11,
            "thirdparties": 2,
            "infostealer_stats": {"RedLine": 4, "Lumma": 2, "UNKNOWN": 1},
            "last_employee_compromised": "2024-04-12T18:43:45+00:00",
            "last_user_compromised": "2025-12-13T18:38:00+00:00",
        },
    },
    {
        "victim": "Telering",
        "domain": "telering.de",
        "attackdate": "2026-08-01T00:00:00+00:00",
        "country": "",
        "activity": "Retail & E-Commerce",
        "infostealer": {
            "employees": 0,
            "users": 4,
            "thirdparties": 0,
            "infostealer_stats": {"UNKNOWN": 2},
            # ⚠️ epoch employe comme « jamais »
            "last_employee_compromised": "1970-01-01T00:00:00+00:00",
            "last_user_compromised": "2023-03-04T17:17:56+00:00",
        },
    },
]


class TestChampsDeBase:
    def test_date_d_attaque_extraite(self):
        """Le gain de DATATION : 22 % de nos documents d'alerte sont dates,
        `attackdate` est renseigne a 100 % chez ransomware.live."""
        intel = parse_victim_intel(PAYLOAD)
        assert intel["assurance-exemple.com"].attack_date == "2026-09-02T00:00:00+00:00"

    def test_secteur_et_pays(self):
        intel = parse_victim_intel(PAYLOAD)
        assert intel["assurance-exemple.com"].activity == "Healthcare"
        assert intel["assurance-exemple.com"].country == "FR"

    def test_pays_vide_devient_none(self):
        """Jamais une chaine vide : « inconnu » doit se distinguer de « vide »."""
        assert parse_victim_intel(PAYLOAD)["telering.de"].country is None


class TestExpositionIdentifiants:
    """Le critere « login / mot de passe », enfin alimente -- mais par des
    COMPTEURS, jamais par des valeurs."""

    def test_exposition_detectee(self):
        assert parse_victim_intel(PAYLOAD)[
            "assurance-exemple.com"
        ].has_credential_exposure

    def test_exposition_privilegiee_distingue_employes_et_clients(self):
        """3 employes exposes chez assih -> interne. 0 employe et 4 clients
        chez telering -> exposition non privilegiee. C'est la distinction
        demandee, posee sur le ROLE, jamais sur la personne."""
        intel = parse_victim_intel(PAYLOAD)
        assert intel["assurance-exemple.com"].privileged_exposure
        assert not intel["telering.de"].privileged_exposure
        assert intel["telering.de"].has_credential_exposure

    def test_familles_de_stealer_nommees(self):
        intel = parse_victim_intel(PAYLOAD)
        assert intel["assurance-exemple.com"].stealer_families == ("Lumma", "RedLine")

    def test_familles_non_informatives_ecartees(self):
        """« UNKNOWN » et « Generic Stealer » ne nomment rien -- les afficher
        ferait passer une absence de mesure pour un resultat."""
        assert parse_victim_intel(PAYLOAD)["telering.de"].stealer_families == ()


class TestEpochNestPasUneDate:
    """⚠️ `1970-01-01` est l'epoch Unix employe comme « jamais ». Le prendre
    pour une date afficherait « compromis depuis 1970 »."""

    def test_epoch_ramene_a_none(self):
        intel = parse_victim_intel(PAYLOAD)
        assert intel["telering.de"].last_employee_compromised is None
        assert intel["telering.de"].last_user_compromised is not None


class TestAucunePII:
    """⚠️ FRONTIERE DE LA REGLE 2. Le contrat ne doit porter QUE des entiers,
    des dates et des libelles -- jamais un identifiant, une adresse ou un
    mot de passe. Verrouille par la FORME du contrat, pas par une relecture."""

    def test_contrat_ne_porte_que_compteurs_dates_et_libelles(self):
        autorises = {
            "attack_date",
            "country",
            "activity",
            "data_size",
            "compromised_employees",
            "compromised_users",
            "compromised_thirdparties",
            "stealer_families",
            "last_employee_compromised",
            "last_user_compromised",
        }
        assert {f.name for f in fields(VictimIntel)} == autorises

    def test_aucune_valeur_brute_recopiee(self):
        """Meme si l'amont ajoutait un champ d'identifiant, il ne serait pas
        lu : le parseur enumere des champs nommes, il ne recopie pas le
        payload."""
        pollue = [
            {
                "domain": "assurance-exemple.com",
                "attackdate": "2026-09-02T00:00:00+00:00",
                "infostealer": {
                    "users": 1,
                    "credentials": ["admin@assurance-exemple.com:Passw0rd!"],
                    "emails": ["root@assurance-exemple.com"],
                },
            }
        ]
        intel = parse_victim_intel(pollue)["assurance-exemple.com"]
        serialise = repr(intel)
        assert "Passw0rd" not in serialise
        assert "admin@assurance-exemple.com" not in serialise
        assert intel.compromised_users == 1


class TestRobustesse:
    def test_payload_inattendu(self):
        for mauvais in (None, {}, "erreur", [{"pas": "un domaine"}]):
            assert isinstance(parse_victim_intel(mauvais), dict)

    def test_infostealer_absent_se_lit_NON_MESURE_pas_zero(self):
        """⚠️ Cas reel depuis ~2026-09-23 : ransomware.live a retire le champ.
        Le ramener a 0 affichait « 0 identifiant expose » sur 49 alertes."""
        intel = parse_victim_intel([{"domain": "x.com", "attackdate": "2026-01-01"}])
        assert not intel["x.com"].has_credential_exposure
        assert not intel["x.com"].privileged_exposure
        assert intel["x.com"].stealer_families == ()
        assert intel["x.com"].compromised_employees is None
        assert intel["x.com"].compromised_users is None
        assert intel["x.com"].compromised_thirdparties is None

    def test_zero_fourni_reste_zero(self):
        intel = parse_victim_intel(
            [{"domain": "x.com", "infostealer": {"employees": 0, "users": 0}}]
        )
        assert intel["x.com"].compromised_employees == 0
        assert intel["x.com"].compromised_users == 0
        # Cle absente du bloc present : non fournie, pas nulle.
        assert intel["x.com"].compromised_thirdparties is None

    def test_compteur_negatif_ou_texte_est_non_mesure(self):
        intel = parse_victim_intel(
            [{"domain": "x.com", "infostealer": {"users": -3, "employees": "beaucoup"}}]
        )
        assert intel["x.com"].compromised_users is None
        assert intel["x.com"].compromised_employees is None


class TestDateDImportEnLot:
    """⚠️ PIEGE MESURE : 57 des 129 victimes d'APT73 (44 %) portent la MEME
    `attackdate` (2026-04-27), dont egov-exemple.sc, finances-exemple.go.ke, media-exemple.ma et telecom-exemple.ma --
    des incidents qui ne se sont evidemment pas produits le meme jour. C'est
    une date d'INDEXATION en lot. Meme famille que le `data-timer` de LockBit :
    un champ present partout, plausible, et qui ne mesure pas ce qu'on croit.

    Les autres gangs mesures restent sous 15 % : le seuil separe bien deux
    regimes, il ne coupe pas au plus juste."""

    @staticmethod
    def _victimes(dates: list[str]) -> list[dict]:
        return [
            {"domain": f"v{i}.com", "attackdate": f"{d}T00:00:00+00:00"}
            for i, d in enumerate(dates)
        ]

    def test_date_massivement_partagee_ecartee(self):
        from app.pipeline.enrich.ransomware_live import batch_indexing_dates

        payload = self._victimes(
            ["2026-04-27"] * 30 + [f"2026-01-{j:02d}" for j in range(1, 21)]
        )
        assert "2026-04-27" in batch_indexing_dates(payload)

    def test_publication_par_lots_diffuse_conservee(self):
        """Un gang qui publie 10 % de ses victimes le meme jour publie par
        lots -- c'est normal, la date reste valable."""
        from app.pipeline.enrich.ransomware_live import batch_indexing_dates

        payload = self._victimes(
            ["2026-08-21"] * 5
            + [f"2026-0{m}-{j:02d}" for m in (1, 2, 3) for j in range(1, 16)]
        )
        assert batch_indexing_dates(payload) == frozenset()

    def test_victime_dans_un_lot_perd_sa_date(self):
        """⚠️ La date est ECARTEE, pas conservee faute de mieux : une date
        fausse se propagerait dans le tri par fraicheur et dans le rapport."""
        payload = self._victimes(
            ["2026-04-27"] * 30 + [f"2026-01-{j:02d}" for j in range(1, 21)]
        )
        intel = parse_victim_intel(payload)
        assert intel["v0.com"].attack_date is None
        assert intel["v30.com"].attack_date is not None

    def test_echantillon_trop_petit_ne_conclut_pas(self):
        """Sous 20 victimes, une part n'est pas significative -- ne pas
        transformer un petit gang en faux positif."""
        from app.pipeline.enrich.ransomware_live import batch_indexing_dates

        assert batch_indexing_dates(self._victimes(["2026-04-27"] * 5)) == frozenset()


class TestSecteurNonInformatif:
    def test_sentinelles_ramenees_a_none(self):
        """« Not Found » et « Other » sont des sentinelles, pas des secteurs --
        mesure : domaine-exemple.co.za rend « Not Found »."""
        intel = parse_victim_intel(
            [
                {"domain": "a.com", "activity": "Not Found"},
                {"domain": "b.com", "activity": "Other"},
                {"domain": "c.com", "activity": "Government & Defense"},
            ]
        )
        assert intel["a.com"].activity is None
        assert intel["b.com"].activity is None
        assert intel["c.com"].activity == "Government & Defense"


class TestRapprochementParNom:
    """Repli par NOM pour les victimes publiees sans domaine (2026-10-01) :
    6 organisations surveillees par leur seule raison sociale restaient sans
    secteur, donc plafonnees a medium."""

    def test_nom_avec_pays_rejoint_le_nom_nu(self):
        """NIGHT SPIRE publie « XYZ Investments(Egypt) », ransomware.live
        range le pays a part et ecrit « XYZ Investments »."""
        from app.pipeline.enrich.ransomware_live import (
            parse_victim_intel_by_name,
            victim_name_keys,
        )

        index = parse_victim_intel_by_name(
            [
                {
                    "victim": "XYZ Investments",
                    "domain": "XYZ Investments",
                    "activity": "Financial Services",
                }
            ]
        )
        cles = victim_name_keys("XYZ Investments(Egypt)")
        assert cles[0] == "xyz investments egypt"  # nom complet d'abord
        trouves = [index[c] for c in cles if c in index]
        assert trouves and trouves[0][0].activity == "Financial Services"

    def test_qualificatif_apres_virgule(self):
        from app.pipeline.enrich.ransomware_live import victim_name_keys

        assert "lamexa" in victim_name_keys("LAMEXA, Egypt")

    def test_egalite_jamais_inclusion(self):
        """« Acme » ne rejoint pas « Acme County Sheriff »."""
        from app.pipeline.enrich.ransomware_live import (
            parse_victim_intel_by_name,
            victim_name_keys,
        )

        index = parse_victim_intel_by_name(
            [{"victim": "Acme County Sheriff", "activity": "Government & Defense"}]
        )
        assert not any(c in index for c in victim_name_keys("Acme"))

    def test_homonymes_gardes_tous_pour_que_l_appelant_refuse(self):
        """Deux victimes du meme nom : l'index les garde TOUTES, l'appelant
        ne doit alors rien conclure (voir `_par_nom`)."""
        from app.pipeline.enrich.ransomware_live import parse_victim_intel_by_name

        index = parse_victim_intel_by_name(
            [
                {"victim": "Acme Holdings", "activity": "Healthcare"},
                {"victim": "Acme Holdings", "activity": "Manufacturing"},
            ]
        )
        assert len(index["acme holdings"]) == 2

    def test_index_par_domaine_inchange(self):
        """L'extraction commune ne change rien a l'index par domaine."""
        intel = parse_victim_intel(PAYLOAD)
        assert intel["assurance-exemple.com"].activity == "Healthcare"


class TestParNomCoteService:
    def test_ambigu_rend_none(self):
        from app.pipeline.enrich.ransomware_live import parse_victim_intel_by_name
        from app.services.victim_intel_service import _par_nom

        index = parse_victim_intel_by_name(
            [
                {"victim": "Acme Holdings", "activity": "Healthcare"},
                {"victim": "Acme Holdings", "activity": "Manufacturing"},
            ]
        )
        assert _par_nom(["Acme Holdings"], index) is None

    def test_unique_rend_les_renseignements(self):
        from app.pipeline.enrich.ransomware_live import parse_victim_intel_by_name
        from app.services.victim_intel_service import _par_nom

        index = parse_victim_intel_by_name(
            [{"victim": "EXEMPLE HOSPITAL", "activity": "Healthcare"}]
        )
        trouve = _par_nom(["EXEMPLE HOSPITAL(Egypt)"], index)
        assert trouve is not None and trouve.activity == "Healthcare"
