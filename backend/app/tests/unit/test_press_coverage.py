"""Tests de la confirmation par la presse (plan de credibilite, phase 1).

Aucun reseau, aucune base : l'analyseur est pur, et le service est exerce sur
une session simulee -- les tests d'integration de ce projet ecrivent encore
dans la base de developpement, ce qui a deja reecrit des alertes reelles."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.pipeline.enrich.ransomware_live import (
    PressCoverage,
    VictimIntel,
    parse_press_coverage,
)
from app.services import victim_intel_service as svc

# Forme REELLE observee sur 393 entrees (2026-09-24) : toujours un objet
# {link, source, summary}. Cas reel : institution-exemple.sn chez krybit.
ARTICLE = "https://lequotidien.sn/nouvelle-cyberattaque-la-cour-des-comptes-touchee/"
FICHE = "https://www.ransomware.live/id/Y291cmRlc2NvbXB0ZXMuc24"

PAYLOAD = [
    {
        "victim": "institution-exemple.sn",
        "domain": "www.institution-exemple.sn",
        "press": {
            "link": FICHE,
            "source": ARTICLE,
            "summary": "Resume redige par un tiers, qui peut nommer des personnes.",
        },
    },
    {"victim": "sans-presse.co.za", "domain": "sans-presse.co.za", "press": None},
]


class TestParsePressCoverage:
    def test_cas_reel_indexe_par_domaine_normalise(self):
        couverture = parse_press_coverage(PAYLOAD)
        assert couverture["institution-exemple.sn"] == PressCoverage(
            source_url=ARTICLE, evidence_url=FICHE
        )

    def test_victime_sans_presse_absente_de_l_index(self):
        """Absence de couverture = absence d'entree, jamais un « faux »."""
        assert "sans-presse.co.za" not in parse_press_coverage(PAYLOAD)

    def test_source_vide_garde_la_fiche_ransomware_live(self):
        """5 cas sur 393 ont `source` vide : la fiche reste une preuve."""
        couverture = parse_press_coverage(
            [
                {
                    "domain": "acme.com",
                    "press": {"link": FICHE, "source": "", "summary": ""},
                }
            ]
        )
        assert couverture["acme.com"] == PressCoverage(
            source_url=None, evidence_url=FICHE
        )

    @pytest.mark.parametrize("payload", [None, {}, "texte", [None, 3, "x"]])
    def test_format_inattendu_rend_un_index_vide(self, payload):
        assert parse_press_coverage(payload) == {}

    def test_entree_press_de_forme_inattendue_ignoree(self):
        assert parse_press_coverage([{"domain": "acme.com", "press": [ARTICLE]}]) == {}


class TestSecuriteDesLiens:
    """⚠️ Ces URL viennent d'un tiers et finissent dans un `href`."""

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "JAVASCRIPT:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "http://abcdefghijklmnop.onion/leak",
            "https://exemple.com/avec espace",
            "//exemple.com/sans-schema",
            "ftp://exemple.com/x",
            "",
        ],
    )
    def test_url_non_citable_rejetee(self, url):
        couverture = parse_press_coverage(
            [
                {
                    "domain": "acme.com",
                    "press": {"link": url, "source": url, "summary": ""},
                }
            ]
        )
        assert couverture == {}

    def test_http_et_https_acceptes(self):
        couverture = parse_press_coverage(
            [
                {
                    "domain": "acme.com",
                    "press": {
                        "link": "http://a.example/x",
                        "source": "https://b.example/y",
                    },
                }
            ]
        )
        assert couverture["acme.com"].source_url == "https://b.example/y"
        assert couverture["acme.com"].evidence_url == "http://a.example/x"


class TestMinimisation:
    def test_le_resume_du_tiers_n_est_pas_repris(self):
        """Le `summary` peut nommer des personnes : seul le lien est garde."""
        assert {f.name for f in fields(PressCoverage)} == {"source_url", "evidence_url"}
        assert "Resume redige" not in repr(parse_press_coverage(PAYLOAD))

    def test_frontiere_de_victimintel_inchangee(self):
        """La presse a son propre contrat : `VictimIntel` reste la frontiere de
        la regle 2 (compteurs, dates, libelles) et n'accueille aucune URL."""
        assert not any("url" in f.name for f in fields(VictimIntel))


# --------------------------------------------------------------------------
# Service, sur session simulee
# --------------------------------------------------------------------------


class _Resultat:
    def __init__(self, alertes):
        self._alertes = alertes

    def scalars(self):
        return iter(self._alertes)


class _SessionSimulee:
    def __init__(self, alertes):
        self.alertes = alertes
        self.commits = 0

    def execute(self, _requete):
        return _Resultat(self.alertes)

    def commit(self):
        self.commits += 1


def _alerte(domaine, gang="krybit", groupes=None, **deja):
    return SimpleNamespace(
        id=domaine,
        domaine=domaine,
        corroborated_group=gang,
        corroborated_groups=groupes if groupes is not None else [gang],
        press_source_url=deja.get("press_source_url"),
        press_evidence_url=deja.get("press_evidence_url"),
        press_confirmed_at=deja.get("press_confirmed_at"),
    )


@pytest.fixture
def brancher(monkeypatch):
    """Branche des charges ransomware.live simulees, par gang."""

    def _brancher(charges: dict):
        monkeypatch.setattr(svc, "payload_rwl", lambda gang: charges.get(gang))
        monkeypatch.setattr(
            svc, "_domaines_de_l_alerte", lambda db, alert_id: [alert_id]
        )

    return _brancher


class TestRefreshPressCoverage:
    def test_confirme_et_date_la_premiere_observation(self, brancher):
        brancher({"krybit": PAYLOAD})
        alerte = _alerte("institution-exemple.sn")
        resultat = svc.refresh_press_coverage(_SessionSimulee([alerte]))
        assert alerte.press_source_url == ARTICLE
        assert alerte.press_evidence_url == FICHE
        assert alerte.press_confirmed_at is not None
        assert (resultat.alerts_confirmed, resultat.newly_confirmed) == (1, 1)

    def test_seconde_passe_ne_redate_pas(self, brancher):
        brancher({"krybit": PAYLOAD})
        premiere = datetime(2026, 9, 1, tzinfo=timezone.utc)
        alerte = _alerte("institution-exemple.sn", press_confirmed_at=premiere)
        resultat = svc.refresh_press_coverage(_SessionSimulee([alerte]))
        assert alerte.press_confirmed_at == premiere
        assert resultat.newly_confirmed == 0

    def test_une_panne_n_efface_jamais_une_confirmation(self, brancher):
        """Gang injoignable : « ne pas avoir consulte n'est pas avoir cherche »."""
        brancher({"autre": []})  # krybit indisponible
        acquise = datetime(2026, 9, 1, tzinfo=timezone.utc)
        alerte = _alerte(
            "institution-exemple.sn",
            press_source_url=ARTICLE,
            press_evidence_url=FICHE,
            press_confirmed_at=acquise,
        )
        alerte.corroborated_groups = ["krybit", "autre"]
        svc.refresh_press_coverage(_SessionSimulee([alerte]))
        assert (alerte.press_source_url, alerte.press_confirmed_at) == (
            ARTICLE,
            acquise,
        )

    def test_entree_disparue_n_efface_pas_la_confirmation(self, brancher):
        brancher({"krybit": [{"domain": "institution-exemple.sn", "press": None}]})
        acquise = datetime(2026, 9, 1, tzinfo=timezone.utc)
        alerte = _alerte(
            "institution-exemple.sn",
            press_source_url=ARTICLE,
            press_confirmed_at=acquise,
        )
        resultat = svc.refresh_press_coverage(_SessionSimulee([alerte]))
        assert alerte.press_source_url == ARTICLE
        assert resultat.alerts_confirmed == 1

    def test_lien_vide_ne_remplace_pas_un_lien_connu(self, brancher):
        brancher(
            {
                "krybit": [
                    {
                        "domain": "institution-exemple.sn",
                        "press": {"link": FICHE, "source": ""},
                    }
                ]
            }
        )
        alerte = _alerte("institution-exemple.sn", press_source_url=ARTICLE)
        svc.refresh_press_coverage(_SessionSimulee([alerte]))
        assert alerte.press_source_url == ARTICLE

    def test_couverture_trouvee_sous_un_gang_secondaire(self, brancher):
        """Victime revendiquee par deux gangs : la presse peut n'etre indexee
        que sous le second."""
        brancher({"lockbit3": [], "krybit": PAYLOAD})
        alerte = _alerte(
            "institution-exemple.sn", gang="lockbit3", groupes=["lockbit3", "krybit"]
        )
        svc.refresh_press_coverage(_SessionSimulee([alerte]))
        assert alerte.press_source_url == ARTICLE

    def test_sans_presse_rien_n_est_ecrit(self, brancher):
        brancher({"krybit": PAYLOAD})
        alerte = _alerte("sans-presse.co.za")
        resultat = svc.refresh_press_coverage(_SessionSimulee([alerte]))
        assert alerte.press_confirmed_at is None
        assert resultat.alerts_confirmed == 0

    def test_aucun_historique_disponible_est_un_echec_signale(self, brancher):
        brancher({})
        resultat = svc.refresh_press_coverage(_SessionSimulee([_alerte("x.com")]))
        assert resultat.success is False
        assert resultat.gangs_unavailable == 1

    def test_gangs_dedoublonnes_principal_en_tete(self):
        alerte = _alerte(
            "x.com", gang="krybit", groupes=["krybit", "lockbit3", "", None]
        )
        assert svc._gangs_de_l_alerte(alerte) == ["krybit", "lockbit3"]
