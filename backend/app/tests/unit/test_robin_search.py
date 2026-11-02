"""Recherche multi-moteurs de sources .onion (robin) — durcissements du
2026-09-30 portés de l'amont. Sans réseau : `_fetch_engine_results` est
remplacé par des résultats en dur."""

from unittest.mock import MagicMock

import pytest

from app.pipeline.collect.robin import query_search as qs


class TestFiltreContenuPedocriminel:
    """Les moteurs .onion indexent ce contenu ; un résultat qui y correspond
    est écarté avant tout affichage. Frontière non négociable (règles 1-2)."""

    @pytest.mark.parametrize(
        "champ,valeur",
        [
            ("title", "CP videos archive"),
            ("title", "csam collection"),
            ("title", "jailbait forum"),
            ("link", "http://abcd.onion/pthc"),
            ("link", "http://xyz.onion/child-porn"),
        ],
    )
    def test_un_indicateur_est_ecarte(self, champ, valeur):
        assert qs.is_abuse_material({champ: valeur}) is True

    @pytest.mark.parametrize(
        "titre",
        [
            "KRYBIT leak site",
            "Children's hospital data breach",  # « children » seul ne matche pas
            "Sunny Kids Daycare Ltd",
            "senegal database dump",
        ],
    )
    def test_un_titre_legitime_passe(self, titre):
        assert (
            qs.is_abuse_material({"title": titre, "link": "http://x.onion/"}) is False
        )

    def test_le_filtre_est_rejoue_dans_search_all_engines(self, monkeypatch):
        monkeypatch.setattr(
            qs, "SEARCH_ENGINES", [{"name": "E", "url": "http://e.onion/?q={query}"}]
        )
        monkeypatch.setattr(
            qs,
            "_fetch_engine_results",
            lambda *a, **k: [
                {
                    "title": "KRYBIT victims",
                    "link": "http://good.onion/a",
                    "engine": "E",
                },
                {"title": "csam links", "link": "http://bad.onion/b", "engine": "E"},
            ],
        )
        liens = [r["link"] for r in qs.search_all_engines("krybit", "krybit")]
        assert liens == ["http://good.onion/a"]


class TestDeduplicationEtLimiteParHote:
    def _canned(self, monkeypatch, results):
        monkeypatch.setattr(
            qs, "SEARCH_ENGINES", [{"name": "E", "url": "http://e.onion/?q={query}"}]
        )
        monkeypatch.setattr(qs, "_fetch_engine_results", lambda *a, **k: list(results))

    def test_les_doublons_de_lien_sont_ecartes(self, monkeypatch):
        self._canned(
            monkeypatch,
            [
                {"title": "a", "link": "http://x.onion/p", "engine": "E"},
                {"title": "a bis", "link": "http://x.onion/p/", "engine": "E"},
            ],
        )
        assert len(qs.search_all_engines("q", "q")) == 1

    def test_un_hote_ne_depasse_pas_la_limite(self, monkeypatch):
        self._canned(
            monkeypatch,
            [
                {"title": f"t{i}", "link": f"http://flood.onion/p{i}", "engine": "E"}
                for i in range(6)
            ],
        )
        gardes = qs.search_all_engines("q", "q")
        assert len(gardes) == qs._MAX_RESULTS_PER_HOST


class TestLectureBornee:
    def test_le_corps_est_plafonne(self):
        response = MagicMock()

        def iter_content(chunk_size):
            # Rend plus que le plafond : on doit s'arrêter avant de tout lire.
            for _ in range((qs._SEARCH_PAGE_MAX_BYTES // chunk_size) + 100):
                yield b"x" * chunk_size

        response.iter_content.side_effect = iter_content
        texte = qs._read_capped(response)
        assert len(texte.encode("utf-8")) < qs._SEARCH_PAGE_MAX_BYTES + 8192
