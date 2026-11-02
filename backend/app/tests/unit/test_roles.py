"""Tests des roles et des gardes d'acces.

⚠️ Le test qui compte le plus est `TestAucuneRouteSansGarde` : il ne verifie
pas un comportement mais une COUVERTURE. Une garde oubliee sur un router ne
fait echouer aucun test de la route voisine -- c'est precisement ainsi qu'un
trou d'acces survit a une suite verte."""

from __future__ import annotations

from app.core.roles import (
    DEFAULT_ROLE,
    PEUT_ADMINISTRER,
    PEUT_TRAITER_LES_ALERTES,
    PEUT_VOIR_LE_CORPUS,
    Role,
    role_de,
)


class TestMoindrePrivilege:
    def test_le_defaut_est_analyste_jamais_admin(self):
        """⚠️ Un compte cree sans role explicite ne doit pas pouvoir supprimer
        une source. Le role qui administre se donne, il ne s'herite pas."""
        assert DEFAULT_ROLE is Role.ANALYST
        assert DEFAULT_ROLE not in PEUT_ADMINISTRER

    def test_valeur_inconnue_retombe_sur_le_role_le_moins_puissant(self):
        """Une ligne alteree en base, ou un role d'une version future non
        deployee, ne doit JAMAIS ouvrir l'administration -- meme doctrine que
        la liste blanche d'actions planifiables, ou une entree inconnue est
        ignoree plutot qu'executee."""
        # ⚠️ « analyste » (orthographe francaise) n'est PAS `analyst` : une
        # faute de frappe dans le role degrade vers `viewer`, jamais vers
        # l'admin. C'est le bon sens de chute.
        for valeur in ("superadmin", "root", "", None, "analyste", "admin;"):
            assert role_de(valeur) not in PEUT_ADMINISTRER, valeur
        assert role_de("bidule") is Role.VIEWER

    def test_valeurs_connues_reconnues_malgre_casse_et_espaces(self):
        assert role_de("ADMIN") is Role.ADMIN
        assert role_de("  analyst ") is Role.ANALYST


class TestPerimetreDesRoles:
    def test_admin_peut_tout_ce_que_fait_l_analyste(self):
        """⚠️ L'admin n'est pas un sur-analyste par magie : l'inclusion est
        ecrite. Une egalite stricte l'exclurait de son propre outil."""
        assert Role.ADMIN in PEUT_TRAITER_LES_ALERTES
        assert Role.ADMIN in PEUT_VOIR_LE_CORPUS

    def test_le_viewer_ne_voit_PAS_le_detail_des_contenus(self):
        """⚠️ Par CONCEPTION, pas par oubli. Le dossier de conception pose que
        le RSSI « ne consulte pas le detail des contenus » et attend une vue
        agregee. Lui ouvrir le corpus exposerait des valeurs masquees et des
        adresses `.onion` a quelqu'un qui n'en a pas l'usage -- le contraire
        de la minimisation (regle 5)."""
        assert Role.VIEWER not in PEUT_VOIR_LE_CORPUS
        assert Role.VIEWER not in PEUT_TRAITER_LES_ALERTES
        assert Role.VIEWER not in PEUT_ADMINISTRER

    def test_l_analyste_n_administre_pas(self):
        assert Role.ANALYST not in PEUT_ADMINISTRER


class TestAucuneRouteSansGarde:
    """⚠️ COUVERTURE, pas comportement. Avant les roles, les 80 endpoints
    etaient accessibles a tout utilisateur authentifie. Ce test echoue si un
    router est ajoute sans garde -- le seul moyen de ne pas redecouvrir le
    trou en production."""

    @staticmethod
    def _routes_effectives():
        """Toutes les routes, avec les dépendances héritées de leur router.

        ⚠️ Depuis FastAPI 0.142 (mise à jour de sécurité du 2026-10-06), un
        router inclus n'est plus aplati dans `app.routes` : il y figure comme
        un `_IncludedRouter` dont `effective_route_contexts()` rend les routes
        réelles. Lire `app.routes` seul faisait examiner ZÉRO route — le témoin
        `examinees > 50` l'a attrapé."""
        from app.main import app

        routes = []
        for route in app.routes:
            if hasattr(route, "effective_route_contexts"):
                routes.extend(route.effective_route_contexts())
            else:
                routes.append(route)
        return routes

    def test_toute_route_api_exige_un_role(self):
        import re

        # `/api/auth` (se connecter) et `/api/health` sont volontairement
        # ouverts : exiger un role pour obtenir un jeton serait circulaire.
        OUVERTES = re.compile(r"^/api/(auth|health)")
        sans_garde = []
        examinees = 0
        for route in self._routes_effectives():
            chemin = getattr(route, "path", "")
            if not chemin.startswith("/api") or OUVERTES.match(chemin):
                continue
            examinees += 1
            deps = getattr(route, "dependencies", [])
            source = " ".join(str(getattr(d, "dependency", d)) for d in deps)
            if "garde" not in source:
                sans_garde.append(f"{list(getattr(route, 'methods', []))} {chemin}")
        # ⚠️ TEMOIN : sans lui, un filtre trop strict ferait passer le test a
        # VIDE -- zero route examinee, zero manquante, verdict vert et
        # couverture nulle. Le corpus reel compte ~80 endpoints.
        assert examinees > 50, f"seulement {examinees} routes examinees"
        assert not sans_garde, "routes sans garde de role : " + ", ".join(sans_garde)

    def test_les_gestes_destructeurs_sont_reserves_a_l_admin(self):
        """Creer, modifier, supprimer une source ou une organisation, et vider
        les alertes : ces gestes ne sont pas ceux d'un analyste qui trie sa
        file. ⚠️ Vider les alertes n'est meme pas reversible par une
        regeneration ordinaire (mesure : 2 recreees sur 32)."""
        attendus = [
            ("DELETE", "/api/alerts"),
            ("DELETE", "/api/documents"),
            ("POST", "/api/sources"),
            ("DELETE", "/api/sources/{source_id}"),
            ("POST", "/api/entities"),
            ("DELETE", "/api/entities/{entity_id}"),
            ("DELETE", "/api/watchlist/{keyword_id}"),
        ]
        for methode, chemin in attendus:
            route = next(
                (
                    r
                    for r in self._routes_effectives()
                    if getattr(r, "path", "") == chemin
                    and methode in getattr(r, "methods", set())
                ),
                None,
            )
            assert route is not None, f"route absente : {methode} {chemin}"
            source = " ".join(
                str(getattr(d, "dependency", d)) for d in route.dependencies
            )
            assert "garde" in source, f"{methode} {chemin} sans garde admin"
