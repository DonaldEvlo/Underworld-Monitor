"""Garde-fou : la page de detail recuperee parle-t-elle de CETTE victime ?

⚠️ Defaut REEL corrige le 2026-09-15. 24 des 83 documents PAYLOAD portaient la
page entiere du site (~32 700 caracteres, les 83 victimes) au lieu de leur
propre victime (~370). Les 24 ne contenaient que **2 corps distincts**.

L'ancien garde-fou testait « la page de detail apporte-t-elle PLUS de texte
que l'apercu ? ». Une page de LISTE en apporte toujours plus : le critere
choisissait donc systematiquement le pire cas, sans jamais lever d'erreur."""

from __future__ import annotations

from app.pipeline.collect.dls.scraper import detail_page_is_about

# Extrait des noms reels de victimes PAYLOAD.
AUTRES = [
    "Qualiflex Datacenter",
    "Hans & Jos. Exemple GmbH",
    "Editora Irmaos Vitale",
    "EXEMPLE International Inc.",
    "Brindle Community School",
    "Exemple Investment Holding",
    "Stucheli Architekten",
    "United Exemple International Trading",
]


class TestPageDeDetailSaine:
    def test_page_qui_nomme_sa_victime_est_acceptee(self):
        texte = (
            "Exemple Investment Holding is a hotel group. The leaked data includes "
            "financial documents and employee records."
        )
        assert detail_page_is_about(texte, "Exemple Investment Holding", AUTRES)

    def test_page_longue_mais_specifique_est_acceptee(self):
        """⚠️ NE PAS revenir a un critere de TAILLE. La page de detail de
        « Exemple Pet Health » (DIRE WOLF) depasse 20 000 caracteres et est
        parfaitement legitime : elle ne cite aucune autre victime. La taille
        ne distingue pas une page riche d'une page de liste."""
        texte = "Exemple Pet Health " + ("description detaillee du butin. " * 800)
        assert len(texte) > 20_000
        assert detail_page_is_about(texte, "Exemple Pet Health", AUTRES)

    def test_mention_fortuite_d_une_autre_victime_toleree(self):
        """Une page peut citer un partenaire ou un rachat sans etre une liste.
        Mesure : les pages saines en citent 0, les listes 79 -- la marge de 3
        ne coute rien."""
        texte = (
            "Exemple Investment Holding, partner of Brindle Community School. "
            "The leaked data includes contracts."
        )
        assert detail_page_is_about(texte, "Exemple Investment Holding", AUTRES)


class TestPageDeListeRejetee:
    def test_page_citant_toutes_les_victimes_est_rejetee(self):
        """Le cas PAYLOAD exact : le site sert la meme page pour chaque
        `/posts/<uuid>` et repartit cote navigateur. L'URL par victime est
        pourtant correcte -- c'est ce qui rendait le defaut invisible."""
        texte = "Nos victimes : " + " ; ".join(AUTRES)
        assert not detail_page_is_about(texte, "Exemple Investment Holding", AUTRES)

    def test_LIMITE_ASSUMEE_une_page_generique_passe_ce_garde_fou(self):
        """⚠️ LIMITE CONNUE, ecrite ici pour ne pas etre redecouverte.

        Une page generique (accueil, page de negociation) ne cite aucune autre
        victime : ce garde-fou la laisse donc passer. C'est le prix de
        l'abandon du critere « la page nomme sa victime », qui rejetait
        714 descriptions valides sur 2383 -- un site de fuite titre par le
        domaine et decrit par la raison sociale.

        Le filet restant est le test de longueur dans l'adaptateur (on ne
        remplace que si la page apporte plus que l'apercu). Si ce cas se
        materialise un jour en base, le corriger par une mesure, pas par une
        intuition."""
        texte = "Bienvenue sur notre blog. Contactez-nous pour negocier."
        assert detail_page_is_about(texte, "Exemple Investment Holding", AUTRES)

    def test_texte_vide_rejete(self):
        assert not detail_page_is_about("", "Exemple Investment Holding", AUTRES)


class TestNomsImbriques:
    """⚠️ Constate sur ORION : « Orion RAAS Group » cohabite avec « Orion
    RAAS ». Une simple inegalite comptait 10 « autres victimes » sur une page
    parfaitement specifique -- 20 faux rejets. Des noms imbriques designent la
    meme organisation."""

    def test_nom_imbrique_ne_compte_pas_comme_autre_victime(self):
        autres = ["Orion RAAS", "Orion RAAS Group Holdings", "Brindle Community School"]
        texte = (
            "Orion RAAS Group orion PUBLISHED Orion RAAS Group Access Hidden Content"
        )
        assert detail_page_is_about(texte, "Orion RAAS Group", autres)


class TestSurCorpusReel:
    """Mesure du 2026-09-15 sur les 2383 descriptions reelles du corpus DLS :
    **24 rejets, exactement les 24 blobs PAYLOAD**, aucun autre.

    Les deux versions precedentes du garde-fou rejetaient respectivement 714 et
    44 descriptions valides -- ces chiffres sont la raison pour laquelle le
    critere ne porte QUE sur le comptage des autres victimes."""

    def test_le_critere_ne_porte_pas_sur_le_nom(self):
        """⚠️ Un site de fuite TITRE par le domaine et DECRIT par la raison
        sociale : `imagerie-exemple.com` est decrit comme « German Imaging Technologies
        (GIT) Dubai LLC ». Exiger que la page nomme sa victime rejetait ce
        contenu parfaitement valide."""
        texte = (
            "German Imaging Technologies (GIT) Dubai LLC is a German-founded "
            "company established in 1999, headquartered in Dubai."
        )
        assert detail_page_is_about(texte, "imagerie-exemple.com", AUTRES)


class TestNomsCourts:
    """Un nom court matche par accident en sous-chaine -- meme prudence que les
    frontieres de mot du classifieur d'annonces."""

    def test_noms_courts_ne_comptent_pas_comme_autres_victimes(self):
        autres = ["In.Sa", "Roof", "ACME", "Exemple Investment Holding"]
        texte = "Roofing and ACME-like products. In.Sa. " * 20 + "Ma Victime SARL"
        assert detail_page_is_about(texte, "Ma Victime SARL", autres)
