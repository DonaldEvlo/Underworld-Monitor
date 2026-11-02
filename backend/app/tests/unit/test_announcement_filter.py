"""Tests du classifieur d'annonces (logique pure, aucun reseau).

Les cas reproduisent des titres REELS du corpus, releves le 2026-08-28 sur
Dread, BreachForums, SPEAR et les sites de fuite."""

import pytest

from app.pipeline.detect.announcement_filter import (
    AnnouncementClass,
    classify_announcement,
    is_content_truncated,
)


class TestExclusions:
    """Le cas fondateur du module : un write-up Hack The Box n'est pas une
    fuite, meme sur un forum de fuites et meme avec du vocabulaire technique."""

    def test_htb_writeup_is_noise(self):
        content = (
            "Titre: HTB - Season 11 - Nimbus - Writeup\n"
            "[apercu invite uniquement -- contenu du post non accessible sans compte]"
        )
        result = classify_announcement("HTB - Season 11 - Nimbus - Writeup", content)
        assert result.verdict is AnnouncementClass.NOISE
        assert "exercice" in result.reason

    @pytest.mark.parametrize(
        "title",
        [
            "Who is the hottest waifu on Chainsaw man?",
            "Make WormGPT your friend for learning hacking quickly",
            "How to earn credits, and safely use our forum.",
            "INSTAGRAM MEGA HACK PACK WITH LOTS OF INSTA HACK TUTORIALS",
            "Dead Island 2 v.7.0.0.1243375",
            "Dark web links directory",
            "looking for music archive",
            "Community Update: Post Submission Guidelines",
            "where do i start?",
        ],
    )
    def test_real_forum_noise_is_rejected(self, title):
        assert classify_announcement(title).verdict is AnnouncementClass.NOISE

    def test_exclusion_wins_over_leak_vocabulary(self):
        """Un tutoriel qui parle de bases de donnees reste un tutoriel :
        l'exclusion doit primer, sinon le vocabulaire technique suffirait a
        faire remonter n'importe quel cours."""
        result = classify_announcement("Tutorial: how to dump a database")
        assert result.verdict is AnnouncementClass.NOISE


class TestLeakDetection:
    @pytest.mark.parametrize(
        "title",
        [
            "[AR] 28GB of Nawaqis.com Database",
            "[FRANCE] hotel-bourse.com Database",
            "GPO.Gov Database - Leaked, Download!",
            "Tinder (dating app) 32 million users DB",
            "UNITED KINGDOM CITIZENS DATABASE | FULLZ INFO",
            "552 - 240K URL:LOG:PASS Sample | Plutonium",
            "Sunac China Holdings - Full Corporate Data Breach",
        ],
    )
    def test_real_leak_titles_are_detected(self, title):
        assert classify_announcement(title).verdict is AnnouncementClass.LEAK

    def test_credential_list_formats_are_detected(self):
        """Mesure du 2026-08-28 : ces formats scoraient 0 alors qu'il s'agit
        d'identifiants voles -- c'est le format dominant sur SPEAR."""
        for title in ("1.7KK url:log:pass By Napoleon", "AlienTXT ULP 500gb"):
            assert classify_announcement(title).verdict is AnnouncementClass.LEAK

    def test_named_victim_domain_adds_weight(self):
        with_domain = classify_announcement("acme-corp.com database")
        without = classify_announcement("some database")
        assert with_domain.score > without.score


class TestSourceType:
    """⚠️ Sur un site de fuite, le titre est souvent une raison sociale nue.
    Sans le drapeau, la mesure du 2026-08-28 ecartait a tort 18 % de ces
    documents -- dont de vraies victimes."""

    def test_bare_company_name_is_not_noise_on_leak_site(self):
        result = classify_announcement(
            "Exemplo Corporation", source_publishes_victims=True
        )
        assert result.verdict is AnnouncementClass.UNCERTAIN
        assert result.verdict is not AnnouncementClass.NOISE

    def test_same_title_on_a_forum_is_not_promoted(self):
        """Le meme titre sur un forum ne beneficie pas de cette indulgence :
        il n'y a aucune raison d'y voir une victime."""
        result = classify_announcement(
            "Exemplo Corporation", source_publishes_victims=False
        )
        assert result.verdict is AnnouncementClass.NOISE

    def test_leak_site_victim_with_domain_is_a_leak(self):
        result = classify_announcement(
            "www.institution-exemple.sn", source_publishes_victims=True
        )
        assert result.verdict is AnnouncementClass.LEAK


class TestTruncatedContent:
    """93 documents sur 93 de BreachForums sont tronques : le savoir change
    la lecture d'un score faible."""

    def test_detects_guest_preview(self):
        assert is_content_truncated(
            "[apercu invite uniquement -- contenu du post non accessible sans compte]"
        )

    def test_flag_is_reported(self):
        result = classify_announcement(
            "kinda old but new", "[apercu invite uniquement]"
        )
        assert result.content_truncated is True

    def test_full_content_is_not_flagged(self):
        assert (
            classify_announcement("un titre", "un contenu complet").content_truncated
            is False
        )

    def test_truncated_body_is_not_scored(self):
        """Le marqueur de troncature ne doit pas etre lu comme du contenu :
        sinon le mot « contenu » ou « compte » pourrait peser dans le score."""
        result = classify_announcement(
            "réunion hebdomadaire",
            "[apercu invite uniquement -- contenu du post non accessible sans compte]",
        )
        assert result.score == 0


class TestUncertainIsNotDiscarded:
    """UNCERTAIN existe pour ne JAMAIS jeter en silence ce qu'on n'a pas su
    classer -- c'est l'ensemble que le LLM tranchera."""

    def test_weak_signal_stays_actionable(self):
        result = classify_announcement("Exemple Communications, Inc.  42M")
        assert result.verdict is AnnouncementClass.UNCERTAIN
        assert result.is_actionable is True

    def test_noise_is_not_actionable(self):
        assert classify_announcement("my intro").is_actionable is False

    def test_empty_title_is_uncertain_not_noise(self):
        assert classify_announcement("").verdict is AnnouncementClass.UNCERTAIN


class TestReasonIsExplicit:
    """Un analyste doit comprendre POURQUOI un document a ete ecarte sans
    relire le code."""

    def test_noise_states_the_category(self):
        assert "exercice" in classify_announcement("Nimbus Writeup").reason

    def test_leak_lists_the_markers(self):
        reason = classify_announcement("[AR] 28GB of Nawaqis.com Database").reason
        assert "volume" in reason or "base" in reason


class TestFraudServicesAreOutOfScope:
    """Signale le 2026-09-02 : les annonces de monetisation frauduleuse et de
    services scoraient LEAK parce qu'elles contiennent du vocabulaire de fuite
    (« CC », « cashout », un volume en Go). Mesure avant correctif : 12 faux
    positifs sur le corpus, dont « UPDATED METHODS OF CARD CASHOUT ».

    Le carding est hors perimetre par decision deja documentee (exclusion de
    markets.md et de BFD Forum, desactivation de DOXBYTE) : `matching.py` ne
    sait pas rattacher une detection `card` a une organisation."""

    @pytest.mark.parametrize(
        "titre",
        [
            "A Newcomer's Carding Dictionary",
            "UPDATED METHODS OF CARD CASHOUT",
            "Carding Cashout - CC to BTC / Step-by-Step Methods",
            "CC TO CRYPTO (Historical Method)",
            "Cashout Service in Australia",
        ],
    )
    def test_carding_is_noise(self, titre):
        result = classify_announcement(titre, "", source_publishes_victims=False)
        assert result.verdict is AnnouncementClass.NOISE
        assert "carding" in result.reason

    @pytest.mark.parametrize(
        "titre,motif",
        [
            ("TRADINGVIEW PREMIUM FRESHLY CRACKED", "contenu pirate"),
            ("ROBUX METHOD GET 100K ROBUX IN DAY !", "monnaie de jeu"),
            ("BYPASSING GMAIL MOBILE VERIFICATION", "contournement"),
            ("550GB Cybersecurity Premium Courses", "tutoriel"),
        ],
    )
    def test_other_out_of_scope_commerce(self, titre, motif):
        result = classify_announcement(titre, "", source_publishes_victims=False)
        assert result.verdict is AnnouncementClass.NOISE
        assert motif in result.reason

    def test_unlock_service_is_excluded_explicitly_not_by_accident(self):
        """Le cas signale. Il sortait deja en NOISE, mais par simple ABSENCE de
        marqueur de fuite (score 0) : la meme annonce citant « database »
        aurait bascule. Il doit desormais etre ecarte par une REGLE."""
        result = classify_announcement(
            "iCLOUD UNLOCK",
            "Having to unlock an iCloud can be more intense than it seem. "
            "Send a DM on TELEGRAM to get started. Full database access.",
            source_publishes_victims=False,
        )
        assert result.verdict is AnnouncementClass.NOISE
        assert "deverrouillage" in result.reason

    def test_a_working_method_is_excluded_in_both_word_orders(self):
        """« MY ONLY WORKING CC TO BTC METHOD » passait : le motif d'origine
        exigeait que « method » PRECEDE « working »."""
        for titre in (
            "MY ONLY WORKING METHOD THAT NEVER FAILS",
            "METHOD 100% WORKING",
        ):
            result = classify_announcement(titre, "", source_publishes_victims=False)
            assert result.verdict is AnnouncementClass.NOISE, titre


class TestExclusionsNeverKillARealVictim:
    """Garde-fou. L'exclusion s'applique au TITRE et AVANT la protection
    `source_publishes_victims` : un motif trop large tuerait donc une vraie
    victime de site de fuite, sans recours.

    Le cas reel qui a servi de controle : « The Methodist Church of Southern
    Africa », victime du gang BEAST (methodist-exemple.org.za, 150 Go annonces). Un
    marqueur « method » pose en sous-chaine l'aurait supprimee -- c'est
    exactement la victime africaine que la plateforme existe pour trouver."""

    def test_methodist_church_is_still_a_leak(self):
        result = classify_announcement(
            "The Methodist Church of Southern Exemple",
            "Victime annoncee: The Methodist Church of Southern Exemple\n"
            "Site: http://www.methodist-exemple.org.za\nVolume annonce: 150GB",
            source_publishes_victims=True,
        )
        assert result.verdict is AnnouncementClass.LEAK

    @pytest.mark.parametrize(
        "raison_sociale",
        [
            "Methodist Hospital Group",
            "Premium Foods Ltd",
            "Unlock Capital Partners",
            "Cashmere Trading Company",
        ],
    )
    def test_company_names_are_not_excluded(self, raison_sociale):
        """Des raisons sociales qui CONTIENNENT un marqueur d'exclusion sans le
        porter comme mot : les frontieres de mot doivent tenir."""
        result = classify_announcement(
            raison_sociale,
            f"Victime annoncee: {raison_sociale}\nVolume annonce: 40GB",
            source_publishes_victims=True,
        )
        assert result.verdict is not AnnouncementClass.NOISE, raison_sociale


class TestGamingAccountsAreOutOfScope:
    """Comptes de joueurs : hors perimetre sur un FORUM, jamais sur un site de
    fuite (decision de projet, 2026-09-18).

    Titres reels du corpus, releves le 2026-09-18."""

    @pytest.mark.parametrize(
        "titre",
        [
            "🎮 [FREE] Gaming Accounts 95K | ROOT SYSTEM | Community Gift Drop 🎮",
            "20000+ FRESHH ROBLOX LOGS",
            "[BUY] Fortnite Dump, Accounts With 200/300/400+ VBUCKS",
            "╰｢✴ ROBLOX ✴｣╯ ACCOUNTS #10",
        ],
    )
    def test_forum_gaming_offer_is_noise(self, titre):
        result = classify_announcement(titre, source_publishes_victims=False)
        assert result.verdict is AnnouncementClass.NOISE, titre
        assert "hors perimetre" in result.reason

    @pytest.mark.parametrize(
        "victime",
        [
            # Victimes AKIRA reelles : « games » seul ne doit rien exclure.
            "Exemple Games, Jouets Exemple, Puzzles Exemple",
            # Editeurs de jeux : entreprises, donc victimes possibles.
            "Riot Games",
            "Rockstar Games",
            "Nintendo of Europe GmbH",
        ],
    )
    def test_game_company_on_leak_site_stays_a_victim(self, victime):
        """⚠️ Le temoin qui justifie la liste reservee aux forums : la meme
        marque, publiee par un site de fuite, EST une victime."""
        result = classify_announcement(
            victime,
            f"Victime annoncee: {victime}\nVolume annonce: 120GB",
            source_publishes_victims=True,
        )
        assert result.verdict is not AnnouncementClass.NOISE, victime

    def test_access_to_a_game_studio_is_not_excluded(self):
        """Un acces a l'infrastructure d'un STUDIO est une compromission
        d'organisation, pas une offre de comptes de joueurs."""
        result = classify_announcement(
            "Selling Access - GitHub - member of major AAA game studio's private org",
            source_publishes_victims=False,
        )
        assert result.verdict is not AnnouncementClass.NOISE


class TestMissingBodyIsNotAVerdict:
    """Un corps non recupere n'est pas un contenu pauvre : c'est une absence
    de mesure, et elle doit etre SIGNALEE.

    Signale a l'usage le 2026-09-21 sur « DATA LINE BANK » (/d/leaks) : le
    collecteur Dread borne les corps par cycle, 134 documents sur 238 n'en
    avaient pas, et AUCUN n'etait marque tronque -- les regles jugeaient donc
    sur le titre en croyant avoir lu le message."""

    CONTENU = (
        "Titre: DATA LINE BANK\nSubdread: /d/leaks\n"
        "[corps du message non recupere -- voir le lien du fil]\n"
        "Lien du fil: http://dread.onion/post/a0696bc460cba61b3348"
    )

    def test_missing_body_is_flagged_as_truncated(self):
        assert is_content_truncated(self.CONTENU) is True

    def test_classification_reports_the_truncation(self):
        result = classify_announcement("DATA LINE BANK", self.CONTENU)
        assert result.content_truncated is True

    def test_a_present_body_is_not_flagged(self):
        result = classify_announcement(
            "DATA LINE BANK",
            "Titre: DATA LINE BANK\nSubdread: /d/leaks\n"
            "Selling a database of 2M bank customers, 14GB, fresh dump.\n"
            "Lien du fil: http://dread.onion/post/x",
        )
        assert result.content_truncated is False
