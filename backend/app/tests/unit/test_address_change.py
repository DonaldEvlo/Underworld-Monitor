"""Changements d'adresse des sources : repérage et décision (2026-10-05)."""

from __future__ import annotations

from app.pipeline.collect import host_aliases
from app.pipeline.collect.address_change import (
    APPLIED,
    PENDING,
    ListEntry,
    announced_in_documents,
    announced_in_page,
    common_victims,
    compare_with_list,
    current_still_works,
    decide,
    host_of,
    list_suggests_move,
    moved_url,
    name_key,
    parse_deepdarkcti,
)
from app.pipeline.collect.dls.scraper import pick_parser

A = "a" * 56 + ".onion"
B = "b" * 56 + ".onion"
C = "c" * 56 + ".onion"


class TestRepérageSurLeSite:
    def test_avis_de_migration(self):
        html = f"<h1>Migration completed</h1><p>New address: {B}</p>"
        assert announced_in_page(html, {A}) == [B]

    def test_une_page_qui_liste_ses_miroirs_n_est_pas_un_demenagement(self):
        html = (
            f"<p>Our mirrors:</p><a href='http://{B}'>1</a><a href='http://{C}'>2</a>"
        )
        assert announced_in_page(html, {A}) == []

    def test_seules_les_adresses_proches_de_l_annonce(self):
        """Cas LockBit réel : la page cite aussi l'adresse .onion de Twitter."""
        html = (
            f"<p>new domain: {B}</p>" + "x" * 2000 + f"<a href='http://{C}'>twitter</a>"
        )
        assert announced_in_page(html, {A}) == [B]

    def test_notre_propre_adresse_n_est_pas_candidate(self):
        assert announced_in_page(f"We have moved to {A}", {A}) == []

    def test_annonce_dans_un_document_cas_lockbit(self):
        docs = [
            ("new blog domain lockbit 5.0", f"visit http://{B}"),
            ("Victim Inc", f"{C}"),
        ]
        annonces = announced_in_documents(docs, {A})
        assert [a.host for a in annonces] == [B]
        assert annonces[0].evidence == "new blog domain lockbit 5.0"


class TestDeepDarkCTI:
    MD = (
        "|Name|Status|User:Password|\n"
        "| ------ | ------ | ------ |\n"
        f"|[DRAGON FORCE](http://{A})|OFFLINE||\n"
        f"| [DRAGON FORCE (mirror)](http://{B}/) | ONLINE |  |\n"
        f"|[AUTRE](http://{C})|ONLINE||\n"
        "|[Clearnet](https://exemple.org)|ONLINE||\n"
    )

    def test_parse_avec_statut(self):
        entrees = parse_deepdarkcti(self.MD)
        assert [(host_of(e.url), e.status) for e in entrees] == [
            (A, "OFFLINE"),
            (B, "ONLINE"),
            (C, "ONLINE"),
        ]

    def test_cle_de_nom(self):
        assert name_key("LOCKBIT 3.0 (New Dark mirror 1) (DLS)") == name_key(
            "LOCKBIT 3.0 (mirror 3)"
        )

    def test_notre_adresse_offline_propose_l_autre(self):
        v = compare_with_list(parse_deepdarkcti(self.MD), "DRAGON FORCE (DLS)", {A})
        assert v.our_status == "OFFLINE"
        assert [host_of(e.url) for e in v.candidates] == [B]
        assert list_suggests_move(v, stale=False)

    def test_notre_adresse_online_on_ne_touche_a_rien(self):
        entrees = [
            ListEntry("X", f"http://{A}", "ONLINE"),
            ListEntry("X", f"http://{B}", "ONLINE"),
        ]
        v = compare_with_list(entrees, "X (DLS)", {A})
        assert not list_suggests_move(v, stale=False)
        # ... sauf si notre collecte ne réussit plus.
        assert list_suggests_move(v, stale=True)

    def test_absente_de_la_liste(self):
        v = compare_with_list([ListEntry("X", f"http://{B}", "ONLINE")], "X", {A})
        assert v.our_status is None and list_suggests_move(v, stale=False)


class TestDecision:
    def test_meme_site_bascule(self):
        d = decide(reachable=True, dedicated_parser=True, parsed=20, common=12)
        assert d.status == APPLIED

    def test_autre_site_du_meme_groupe_reste_a_examiner(self):
        """Cas LockBit 5 : le site répond, publie des victimes, mais pas les nôtres."""
        d = decide(reachable=True, dedicated_parser=True, parsed=30, common=1)
        assert d.status == PENDING and "AUTRE site" in d.reason

    def test_l_adresse_actuelle_fonctionne_encore_pas_de_bascule(self):
        """Cas LockBit 3 -> 5 : même avec des victimes communes, une source qui
        publie toujours ne déménage pas."""
        d = decide(
            reachable=True,
            dedicated_parser=True,
            parsed=30,
            common=10,
            current_works=True,
        )
        assert d.status == PENDING and "fonctionne encore" in d.reason

    def test_adresse_actuelle_hors_service(self):
        assert not current_still_works("", None)
        assert not current_still_works("<h1>Migration completed</h1>", None)
        assert not current_still_works("<html>liste</html>", 0)  # plus de victimes
        assert current_still_works("<html>liste</html>", 12)
        assert current_still_works("<html>forum</html>", None)

    def test_un_bandeau_new_domain_sur_un_site_qui_publie_n_eteint_rien(self):
        """Cas LockBit 3 réel : bandeau « new domain » + 508 victimes."""
        assert current_still_works("<div>new domain: ...</div>" + "x" * 100, 508)

    def test_forum_jamais_automatique(self):
        d = decide(reachable=True, dedicated_parser=False, parsed=0, common=0)
        assert d.status == PENDING

    def test_injoignable(self):
        assert (
            decide(reachable=False, dedicated_parser=True, parsed=0, common=0).status
            == PENDING
        )

    def test_victimes_communes_normalisees(self):
        assert (
            common_victims(["www.Acme.com", "Tohpe Corp"], ["acme.com", "TOHPE CORP"])
            == 2
        )

    def test_url_deplacee_garde_le_chemin(self):
        assert moved_url(f"http://{A}/blog/", B) == f"http://{B}/blog/"


class TestAlias:
    def setup_method(self):
        host_aliases.configure(None)

    def test_le_parser_suit_la_source_demenagee(self):
        """⚠️ Sans alias, le nouvel hôte retombe sur le collecteur générique."""
        lockbit = "lockbit3753ekiocyo5epmpy6klmejchjtzddoekjlnt6mu3qh4de2id.onion"
        assert pick_parser(f"http://{B}") is None
        with host_aliases.temporary({B: lockbit}):
            assert pick_parser(f"http://{B}") is not None
        assert pick_parser(f"http://{B}") is None

    def test_pas_de_boucle(self):
        with host_aliases.temporary({A: B, B: A}):
            assert host_aliases.canonical_host(A) in (A, B)

    def test_chargeur_en_panne_garde_les_derniers_alias(self, monkeypatch):
        etat = {"panne": False}

        def chargeur() -> dict[str, str]:
            if etat["panne"]:
                raise RuntimeError("base indisponible")
            return {B: A}

        host_aliases.configure(chargeur)
        try:
            assert host_aliases.canonical_host(B) == A
            etat["panne"] = True
            host_aliases.invalidate()
            assert host_aliases.canonical_host(B) == A
        finally:
            host_aliases.configure(None)
