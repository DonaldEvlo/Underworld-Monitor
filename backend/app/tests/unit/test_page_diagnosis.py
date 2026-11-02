"""Diagnostic d'une page qui n'a rien donne.

⚠️ Ce module existe parce qu'un message unique -- « source injoignable ou
vide » -- couvrait des situations aux suites opposees (mesure du 2026-09-04) :
DRAGON FORCE avait DEMENAGE et annoncait sa nouvelle adresse, XSSF exigeait un
CAPTCHA. L'un se corrige en une minute, l'autre ne se corrige pas.
"""

import pytest

from app.pipeline.collect.page_diagnosis import diagnostiquer_page


class TestAbsenceDeReponse:
    @pytest.mark.parametrize("vide", [None, "", "   \n  "])
    def test_rien_recu_dit_injoignable(self, vide):
        assert "injoignable" in diagnostiquer_page(vide)


class TestCasReels:
    def test_migration_dragonforce_donne_la_nouvelle_adresse(self):
        """L'information utile n'est pas « ça a échoué » mais « c'est là-bas »."""
        nouvelle = "xjhmtitnrdrgzw4vmsghirdoo2fk35a3tzj4enlmah4pvehdspydsiyd.onion"
        message = diagnostiquer_page(
            "<title>DragonForce | Migration completed</title>"
            f"<p>Blog is available now - {nouvelle}</p>"
        )
        assert "déménagé" in message
        assert nouvelle in message

    def test_captcha_xssf_est_annonce_comme_non_contournable(self):
        """⚠️ Reconnaitre un anti-bot sert a S'ARRETER, jamais a passer outre
        (regle 1). Le message doit le dire, sinon quelqu'un cherchera comment
        le franchir."""
        message = diagnostiquer_page(
            "<title>XSSF FORUM - Access Verification</title>"
            "<p>DDoS Protection. Please complete the CAPTCHA below.</p>"
        )
        assert "anti-bot" in message
        assert "contournable" in message

    def test_barriere_par_empreinte_de_navigateur_sans_captcha(self):
        """⚠️ Mesure du 2026-10-08 sur le site de « the gentlemen » : une page
        de 8 150 octets titree « Gentlecloud Protection », SANS captcha ni
        formulaire, qui calcule une empreinte en JavaScript puis appelle
        `/challenge/get_challenge`.

        Avant ce correctif, le diagnostic rendu etait « structure probablement
        modifiee » : on aurait cherche un correctif de parser pour une
        barriere qu'on ne franchira jamais (regle 1). C'est le cas le plus
        couteux -- un diagnostic faux envoie travailler dans le vide."""
        message = diagnostiquer_page(
            "<title>Gentlecloud Protection</title>"
            '<p class="subtitle">Verifying your browser...</p>'
            "<script>const resp = await fetch('/challenge/get_challenge');</script>"
        )
        assert "anti-bot" in message
        assert "contournable" in message
        assert "Gentlecloud" in message

    def test_une_page_de_victimes_normale_n_est_PAS_prise_pour_un_anti_bot(self):
        """Temoin : les marqueurs d'empreinte sont precis. Un marqueur trop
        large ferait declarer « barriere » un site qui publie parfaitement,
        et la source serait abandonnee a chaque cycle."""
        message = diagnostiquer_page(
            "<title>Leaks Blog</title>"
            "<div class='post'><div class='post-title'>acme.com</div>"
            "<p>Browse our verified leaks. 400 GB.</p></div>"
        )
        assert "anti-bot" not in message


class TestAutresBarrages:
    def test_cloudflare(self):
        assert "Cloudflare" in diagnostiquer_page(
            "<title>Attention Required</title><p>cloudflare</p>"
        )

    def test_authentification(self):
        message = diagnostiquer_page(
            "<title>Login</title><input type='password' name='password'>"
        )
        assert "authentification" in message

    def test_javascript_requis(self):
        message = diagnostiquer_page("<p>Please enable javascript to continue</p>")
        assert "JavaScript" in message

    def test_page_servie_mais_non_reconnue(self):
        """Le cas le plus insidieux : rien ne bloque, le site a simplement
        change de structure. Cela demande un correctif de code, pas une
        nouvelle tentative -- le message doit orienter vers le bon geste."""
        message = diagnostiquer_page("<html><body><div>rien d'exploitable</div></body>")
        assert "structure" in message

    def test_priorite_a_l_anti_bot_sur_le_reste(self):
        """Une page de captcha mentionne souvent JavaScript : le motif le plus
        specifique doit trancher, sinon le diagnostic est juste mais inutile."""
        message = diagnostiquer_page(
            "<p>Please enable javascript and complete the CAPTCHA</p>"
        )
        assert "anti-bot" in message

    def test_titre_de_la_page_est_rapporte(self):
        """Sans le titre servi, l'analyste doit rouvrir le site par lui-meme."""
        assert "Access Verification" in diagnostiquer_page(
            "<title>Access Verification</title><p>captcha</p>"
        )
