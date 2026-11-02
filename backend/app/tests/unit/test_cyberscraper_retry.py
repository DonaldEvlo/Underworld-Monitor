"""Le retry du collecteur generique doit REELLEMENT rejouer.

⚠️ Defaut corrige le 2026-09-04, signale depuis le 2026-08-19 sans etre traite
(CONTRIBUTING.md §8) : `_fetch` etait decore par `@with_retry` mais RENDAIT son echec
(`None`, ou une chaine « Error: … »). Or tenacity ne rejoue que sur exception.
Le decorateur etait donc en place, visible dans le code, et n'avait jamais
rejoue une seule tentative -- un echec silencieux au sens strict : rien ne
distingue « 3 tentatives epuisees » de « aucune tentative ».
"""

from unittest.mock import patch

import pytest

from app.pipeline.collect.cyberscraper.adapter import (
    CyberScraperCollector,
    _TransientFetchError,
)


class TestLeRetryEstReellementArme:
    def _collecteur(self):
        return CyberScraperCollector()

    @pytest.mark.parametrize(
        "reponse", [None, "", "   \n  ", "Error: connection refused"]
    )
    def test_un_echec_leve_au_lieu_de_rendre_none(self, reponse):
        """Les quatre formes d'echec du scraper sous-jacent doivent lever.

        ⚠️ La page VIDE a ete trouvee par ce test : `[""]` passait le controle
        (liste non vide, chaine ne commencant pas par « Error: ») et etait
        rendue comme du contenu, donc jamais rejouee -- alors qu'une reponse
        vide est le symptome typique d'un rendu incomplet sur Tor.
        """
        with patch(
            "app.pipeline.collect.cyberscraper.adapter.asyncio.run",
            return_value=[reponse] if reponse is not None else [],
        ), patch("app.pipeline.collect.cyberscraper.adapter.polite_delay"):
            with pytest.raises(_TransientFetchError):
                # `__wrapped__` : la fonction NON decoree. On verifie la
                # levee sans subir les 3 tentatives et leurs attentes
                # exponentielles -- le comptage des tentatives est l'objet du
                # test suivant.
                CyberScraperCollector._fetch.__wrapped__(
                    self._collecteur(), "https://exemple.test", False
                )

    def test_le_decorateur_rejoue_bien_trois_fois(self):
        """Le point central : compter les tentatives REELLES.

        Avant correctif ce compteur valait 1 -- le retry etait decoratif.
        """
        appels = {"n": 0}

        def _echoue(*_args, **_kwargs):
            appels["n"] += 1
            return ["Error: boom"]

        with patch(
            "app.pipeline.collect.cyberscraper.adapter.asyncio.run", _echoue
        ), patch("app.pipeline.collect.cyberscraper.adapter.polite_delay"), patch(
            "app.pipeline.collect.cyberscraper.adapter.build_scraper_config"
        ), patch(
            "app.pipeline.collect.cyberscraper.adapter.PlaywrightScraper"
        ), patch(
            "app.pipeline.collect.cyberscraper.adapter.build_socks5_proxy_url"
        ), patch(
            "app.pipeline.collect.cyberscraper.adapter.wait_exponential_jitter",
            create=True,
        ):
            with pytest.raises(Exception):
                self._collecteur()._fetch("https://exemple.test", False)
        assert appels["n"] == 3

    def test_un_contenu_valide_est_rendu_tel_quel(self):
        """Garde-fou : le correctif ne doit pas transformer un succes en
        echec. « Error: » n'est refuse qu'en TETE de chaine."""
        with patch(
            "app.pipeline.collect.cyberscraper.adapter.asyncio.run",
            return_value=["<html>Error: dans le corps, pas au debut</html>"],
        ), patch("app.pipeline.collect.cyberscraper.adapter.polite_delay"), patch(
            "app.pipeline.collect.cyberscraper.adapter.build_scraper_config"
        ), patch(
            "app.pipeline.collect.cyberscraper.adapter.PlaywrightScraper"
        ), patch(
            "app.pipeline.collect.cyberscraper.adapter.build_socks5_proxy_url"
        ):
            contenu = self._collecteur()._fetch("https://exemple.test", False)
        assert contenu.startswith("<html>")
