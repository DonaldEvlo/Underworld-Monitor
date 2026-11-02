"""Tests des 4 parsers DLS ajoutes le 2026-10-08 : INC RANSOM, RANSOMHOUSE,
DEADLOCK, ARCUS MEDIA.

Aucun test ne touche le reseau. Les charges utiles reproduisent la structure
REELLE relevee le 2026-10-08 sur chaque site via Tor : INC RANSOM et
RANSOMHOUSE servent du JSON (855 et 30 entrees), DEADLOCK un blog maison
(`div.post`, 10 par page) et ARCUS MEDIA un WordPress (`article.post`, 50 sur
l'accueil).

⚠️ Ces 4 gangs ont ete choisis sur une MESURE, pas sur une intuition : ils
portent 21 des 173 victimes africaines des 12 derniers mois (ransomware.live)
qu'aucune de nos sources ne voyait. « the gentlemen », pourtant premier en
volume avec 27 victimes, est exclu : son site est ferme par une barriere
d'empreinte de navigateur, non contournable (regle 1).

Chaque piege mesure sur le site reel est verrouille par un test nomme : ce
sont eux qui doivent echouer si un jour la structure change.
"""

import json

from app.pipeline.collect.dls.scraper import (
    PENDING,
    PUBLISHED,
    _PARSERS,
    listing_urls,
    parse_arcusmedia,
    parse_deadlock,
    parse_incransom,
    parse_ransomhouse,
    pick_parser,
)

INC_URL = "http://incbacg6bfwtrlzwdbqc55gsfl763s3twdtwhp27dzuik6s6rwdcityd.onion"
INC_BLOG_URL = "http://incblog6qu4y4mm4zvw5nrmue6qbwtgjsxpw6b7ixzssu36tsajldoad.onion"
RH_URL = "http://zohlm7ahjwegcedoz7lrdrti7bvpofymcayotp744qhx6gjmxbuo2yid.onion"
DEADLOCK_URL = "http://deadblogdbdu5wprek7wa2o4ce7rnt6u6ntqeud3hzjjcveosgpsqqqd.onion"
ARCUS_URL = "http://arcuufpr5xxbbkin4mlidt7itmr6znlppk63jbtkeguuhszmc5g7qdyd.onion"


# --------------------------------------------------------------------------
# INC RANSOM : API JSON
# --------------------------------------------------------------------------
# Structure reelle : les valeurs sont URL-encodees, `description` est une
# LISTE de paragraphes, `createdAt` et `leakAt` sont en millisecondes.
# `createdAt = 1791380096782` -> 2026-10-07 ; `leakAt = 1752115680000` ->
# 2025-07-10, soit plus d'un an AVANT la creation de l'annonce : les deux
# champs ne decrivent pas le meme fait.
INC_PAYLOAD = {
    "type": True,
    "message": "Success: got announcements.",
    "payload": {
        "length": 855,
        "announcements": [
            {
                "_id": "6ac64a809cd108bf26a28ae3",
                "company": {
                    "company_name": "The%20New%20Exemple%20School",
                    "country": "US",
                    "revenue": 6200000,
                },
                "categories": ["Proof", "Encrypted"],
                "description": [
                    "The%20New%20Exemple%20School%20is%20an%20independent%20day%20school",
                    "%20located%20in%20Richmond%2C%20VA.%20400%20GB%20exfiltres.",
                ],
                "visits": 9999,
                "leakAt": 1752115680000,
                "createdAt": 1791380096782,
                "updatedAt": 1791408834783,
            },
            {
                "_id": "6aad206a9cd108bf2661a43a",
                "company": {
                    "company_name": "www.camping-exemple.com",
                    "country": "NL",
                    "revenue": 50000000,
                },
                "categories": ["Encrypted"],
                "description": ["Dutch%20tour%20operator."],
                "visits": 8927,
                "createdAt": 1789730922739,
            },
            {"_id": "sans-societe", "company": {}, "description": []},
        ],
    },
}


class TestIncRansom:
    def _victimes(self, charge=None):
        return parse_incransom(json.dumps(charge or INC_PAYLOAD), INC_URL)

    def test_extrait_une_victime_par_annonce_et_decode_les_noms(self):
        """Sans `unquote`, le nom resterait `The%20New%20Exemple%20School`
        et ne matcherait aucun selecteur d'entite."""
        victimes = self._victimes()
        assert len(victimes) == 2  # la 3e annonce n'a pas de nom de societe
        assert victimes[0].name == "The New Exemple School"
        assert "independent day school" in (victimes[0].description or "")

    def test_la_date_vient_de_createdAt(self):
        victimes = self._victimes()
        assert victimes[0].published_at is not None
        assert victimes[0].published_at.strftime("%Y-%m-%d") == "2026-10-07"

    def test_leakAt_n_est_JAMAIS_pris_pour_la_date_de_publication(self):
        """⚠️ Piege mesure : `leakAt` vaut 2025-07-10 pour une annonce creee le
        2026-10-07. Une date fausse est pire qu'une date absente -- elle se
        propage dans le tri par fraicheur, la fenetre d'alerting et le rapport
        PDF."""
        victimes = self._victimes()
        assert victimes[0].published_at.year == 2026
        assert victimes[0].published_at.strftime("%Y") != "2025"

    def test_visits_n_entre_PAS_dans_la_description(self):
        """⚠️ `visits` change a chaque consultation (809, 946, 8927 mesures).
        Recopie dans le contenu, il changerait le `content_hash` et la
        victime serait recreee a chaque collecte -- defaut ORION, 111
        documents pour 12 victimes."""
        for victime in self._victimes():
            assert "9999" not in (victime.description or "")
            assert "8927" not in (victime.description or "")

    def test_le_site_n_est_remonte_que_si_le_nom_EST_un_domaine(self):
        """Ce gang titre indifferemment par le domaine ou par la raison
        sociale : inventer un site ferait porter une detection `domain` a une
        chaine qui n'en est pas une."""
        victimes = self._victimes()
        assert victimes[0].site is None  # « The New Exemple School »
        assert victimes[1].site == "http://www.camping-exemple.com"

    def test_le_volume_annonce_est_extrait_de_la_description(self):
        assert self._victimes()[0].volume == "400 GB"

    def test_une_reponse_qui_n_est_pas_du_JSON_ne_leve_pas(self):
        """L'appelant (adapter) leve alors avec le diagnostic de la page, qui
        dira si le site a demenage ou s'est ferme. Un parser qui leve ici
        ferait perdre ce diagnostic."""
        assert parse_incransom("<html>Access denied</html>", INC_URL) == []
        assert parse_incransom("", INC_URL) == []
        assert parse_incransom(json.dumps({"payload": {}}), INC_URL) == []

    def test_les_DEUX_adresses_du_gang_choisissent_le_meme_parser(self):
        """⚠️ Le piege du miroir s'est produit trois fois (DARKNET ARMY,
        DRAGON FORCE) : mapper une seule adresse ferait retomber l'autre sur
        le collecteur generique, qui rend un blob unique sans erreur."""
        assert pick_parser(INC_URL) is parse_incransom
        assert pick_parser(INC_BLOG_URL) is parse_incransom

    def test_la_pagination_est_construite_meme_depuis_l_adresse_nue(self):
        """La source peut etre declaree avec la seule adresse du site : le
        chemin de l'API est construit ici, donc un changement de miroir
        n'oblige pas a reecrire l'URL stockee."""
        urls = listing_urls(INC_URL)
        assert len(urls) == 3
        assert all("/api/v1/blog/get/announcements" in u for u in urls)
        assert "page=1&perPage=30" in urls[0]
        assert "page=3&perPage=30" in urls[2]
        # Depuis une URL qui porte deja le chemin de l'API, pas de doublon.
        assert listing_urls(f"{INC_URL}/api/v1/blog/get/announcements") == urls


# --------------------------------------------------------------------------
# RANSOMHOUSE : API JSON
# --------------------------------------------------------------------------
# Structure reelle : `data` porte 30 entrees dont la PREMIERE est une
# banniere d'actualite. Mesure des statuts sur les 30 : EVIDENCE+NOT YET 17,
# DISCLOSED+date 8, DISCLOSED+NOT YET 4 (contradictoires).
RH_PAYLOAD = {
    "views": "3652097",
    "errors": [],
    "data": [
        {
            "id": "victime-publiee",
            "header": "Neinver",
            "url": "https://www.immobilier-exemple.com/",
            "revenue": "92.4 M$",
            "employees": 350,
            "info": "NEINVER est un operateur de centres commerciaux.",
            "status": "DISCLOSED",
            "published": "16/02/2026",
            "action": "Encrypted",
            "actionDate": "21/08/2026",
            "volume": "~",
            "views": 202458,
        },
        {
            # ⚠️ La banniere n'est PAS en premiere position ici : elle doit
            # etre reconnue par son `display`, pas par son rang.
            "id": "banniere",
            "display": "animated",
            "header": "HOT NEWS",
            "info": "Victime A Status: EVIDENCE, Victime B Status: EVIDENCE",
            "url": "",
            "views": 523324,
        },
        {
            "id": "victime-en-attente",
            "header": "Pertamina",
            "url": "https://www.energie-exemple.com/",
            "info": "Pertamina est une compagnie energetique. 120 GB.",
            "status": "EVIDENCE",
            "published": "NOT YET",
            "volume": "~",
            "views": 21825,
        },
        {
            "id": "statuts-contradictoires",
            "header": "Terca",
            "url": "https://www.ceramique-exemple.com.br/",
            "info": "Fabricant de materiaux.",
            "status": "DISCLOSED",
            "published": "NOT YET",
            "views": 5,
        },
    ],
}


class TestRansomHouse:
    def _par_nom(self):
        victimes = parse_ransomhouse(json.dumps(RH_PAYLOAD), RH_URL)
        return {v.name: v for v in victimes}

    def test_la_banniere_d_actualite_n_est_PAS_une_victime(self):
        """⚠️ Elle recapitule les trois dernieres victimes : l'enregistrer
        creerait un document fourre-tout -- exactement le blob que ce module
        existe pour eviter -- et son texte changerait a chaque nouvelle
        victime, donc son `content_hash` aussi."""
        victimes = parse_ransomhouse(json.dumps(RH_PAYLOAD), RH_URL)
        assert len(victimes) == 3
        assert "HOT NEWS" not in {v.name for v in victimes}

    def test_la_banniere_est_reconnue_par_son_display_pas_par_son_rang(self):
        """Temoin : dans cette charge utile elle est en DEUXIEME position.
        Un filtre sur l'index perdrait la premiere vraie victime le jour ou
        le site reordonne sa liste."""
        victimes = parse_ransomhouse(json.dumps(RH_PAYLOAD), RH_URL)
        assert victimes[0].name == "Neinver"

    def test_le_site_de_la_victime_vient_du_champ_url(self):
        """C'est ce qui fait de ce gang une source utile : 29 victimes sur 29
        portent un domaine, donc rattachable par `matching.py`."""
        assert self._par_nom()["Neinver"].site == "https://www.immobilier-exemple.com/"

    def test_la_date_se_lit_JOUR_avant_MOIS(self):
        """⚠️ `16/02/2026` est le 16 fevrier, pas le 2 mars. Des valeurs
        relevees comme `21/08/2026` prouvent l'ordre (il n'y a pas de 21e
        mois) -- meme famille que le format de Dread."""
        date = self._par_nom()["Neinver"].published_at
        assert (date.year, date.month, date.day) == (2026, 2, 16)

    def test_une_date_de_publication_vaut_PUBLISHED(self):
        victime = self._par_nom()["Neinver"]
        assert victime.publication_status == PUBLISHED
        assert "16/02/2026" in (victime.publication_evidence or "")

    def test_NOT_YET_concordant_avec_EVIDENCE_vaut_PENDING(self):
        victime = self._par_nom()["Pertamina"]
        assert victime.publication_status == PENDING
        assert victime.published_at is None

    def test_des_statuts_CONTRADICTOIRES_laissent_le_statut_INCONNU(self):
        """⚠️ Mesure du 2026-10-08 : 4 entrees sur 30 disent a la fois
        « DISCLOSED » et « NOT YET ». On ne tranche pas a la place du gang --
        NULL se lit « pas evalue », jamais « aucun » (meme convention que
        `corroboration_status`)."""
        victime = self._par_nom()["Terca"]
        assert victime.publication_status is None
        assert victime.publication_evidence is None

    def test_le_volume_tilde_n_est_pas_un_volume(self):
        """`~` vaut `~` sur 29 entrees sur 30 : « non precise ». Le reprendre
        remplirait le champ volume de tildes, qui alimentent la gravite."""
        assert self._par_nom()["Neinver"].volume is None
        # Un volume reellement annonce dans le texte est en revanche garde.
        assert self._par_nom()["Pertamina"].volume == "120 GB"

    def test_actionDate_n_est_pas_la_date_de_publication(self):
        """`actionDate` est la date de l'ATTAQUE (meme distinction que
        `attackdate` et `discovered` chez ransomware.live)."""
        victime = self._par_nom()["Neinver"]
        assert victime.published_at.month == 2  # 16/02, pas le 21/08
        assert "21/08/2026" in (victime.description or "")

    def test_les_compteurs_de_vues_n_entrent_pas_dans_la_description(self):
        for victime in parse_ransomhouse(json.dumps(RH_PAYLOAD), RH_URL):
            assert "202458" not in (victime.description or "")
            assert "3652097" not in (victime.description or "")

    def test_une_seule_URL_de_liste_est_demandee(self):
        assert listing_urls(RH_URL) == [f"{RH_URL}/a"]


# --------------------------------------------------------------------------
# DEADLOCK : blog maison
# --------------------------------------------------------------------------
# Structure reelle : `div.post`, le statut est un `span.badge` qui affiche
# soit « Published » (classe `badge pub`) soit un COMPTE A REBOURS
# « Publishes after: 6d 0h 47m ».
DEADLOCK_HTML = """
<div class="posts">
  <div class="post">
    <div class="post-img"><span class="badge">Publishes after: <b>6d 0h 47m</b></span></div>
    <div class="post-body">
      <div class="post-title font">Calder Argento</div>
      <p class="post-text">Entreprise familiale italienne fondee en 1948. 500GB.</p>
    </div>
  </div>
  <div class="post even">
    <div class="post-img"><span class="badge pub">Published</span></div>
    <div class="post-body">
      <div class="post-title font">FBC</div>
      <p class="post-text">Furniture Bargaining Council, Afrique du Sud. web.mobilier-exemple.co.za</p>
    </div>
  </div>
  <div class="post"><div class="post-body"><div class="autre">sans titre</div></div></div>
</div>
<a class="pg" href="?page=0">1</a><a class="pg" href="?page=1">2</a>
"""


class TestDeadlock:
    def _victimes(self):
        return parse_deadlock(DEADLOCK_HTML, DEADLOCK_URL)

    def test_une_victime_par_post_et_le_bloc_sans_titre_est_ignore(self):
        victimes = self._victimes()
        assert [v.name for v in victimes] == ["Calder Argento", "FBC"]

    def test_le_statut_se_lit_sur_la_CLASSE_du_badge(self):
        victimes = self._victimes()
        assert victimes[0].publication_status == PENDING
        assert victimes[1].publication_status == PUBLISHED

    def test_le_COMPTE_A_REBOURS_n_entre_jamais_dans_la_description(self):
        """⚠️ « 6d 0h 47m » change a chaque consultation. Repris dans le
        contenu, il ferait varier le `content_hash` et recreerait la victime a
        chaque collecte : defaut ORION par un autre chemin."""
        for victime in self._victimes():
            texte = f"{victime.description or ''} {victime.publication_evidence or ''}"
            assert "6d" not in texte
            assert "47m" not in texte

    def test_ce_site_ne_date_rien_et_on_ne_l_invente_pas(self):
        """La fraicheur retombe alors sur `COALESCE(published_at,
        fetched_at)` -- comportement voulu pour une source qui ne date
        rien."""
        assert all(v.published_at is None for v in self._victimes())

    def test_le_domaine_de_la_victime_reste_dans_la_description(self):
        """Ce gang ne publie pas le site de ses victimes : le domaine, quand
        il apparait, est DANS le texte. C'est pourquoi la description est
        conservee entiere."""
        assert "web.mobilier-exemple.co.za" in (self._victimes()[1].description or "")

    def test_la_pagination_commence_a_ZERO(self):
        """Relevee sur les liens `a.pg` du site : `?page=0` a `?page=10`.
        Commencer a 1 sauterait la page la plus recente."""
        urls = listing_urls(DEADLOCK_URL)
        assert urls[0].endswith("?page=0")
        assert len(urls) == 3


# --------------------------------------------------------------------------
# ARCUS MEDIA : WordPress
# --------------------------------------------------------------------------
# Structure reelle : `article.post`, la categorie est portee par la classe de
# l'article (`category-leaked`, `category-new`), et DEUX `<time>` cohabitent.
ARCUS_HTML = """
<main>
  <article class="post-813 post type-post status-publish hentry category-leaked layout-grid" id="post-813">
    <div class="content">
      <h2 class="blog-entry-title entry-title is-h4">
        <a href="/?p=813" rel="bookmark">Exemple&rsquo;s Computing</a>
      </h2>
      <ul class="nv-meta-list">
        <li class="meta date posted-on">
          <time class="entry-date published" content="2026-09-19" datetime="2026-09-19T15:30:10+00:00">September 19, 2026</time>
          <time class="updated" datetime="2026-10-02T15:56:34+00:00">October 2, 2026</time>
        </li>
      </ul>
      <div class="excerpt-wrap entry-summary"><p>Donnees internes, 80 GB.</p></div>
    </div>
  </article>
  <article class="post-822 post type-post hentry category-new layout-grid" id="post-822">
    <div class="content">
      <h2 class="entry-title"><a href="/?p=822">Exemplo Capas</a></h2>
      <time class="entry-date published" datetime="2026-09-27T11:36:16+00:00">September 27, 2026</time>
      <div class="entry-summary"><p>Fabricant bresilien.</p></div>
    </div>
  </article>
  <article class="post type-post hentry"><div class="content">sans titre</div></article>
</main>
"""


class TestArcusMedia:
    def _victimes(self):
        return parse_arcusmedia(ARCUS_HTML, ARCUS_URL)

    def test_une_victime_par_article_et_le_bloc_sans_titre_est_ignore(self):
        victimes = self._victimes()
        assert [v.name for v in victimes] == [
            "Exemple’s Computing",
            "Exemplo Capas",
        ]

    def test_la_date_de_PUBLICATION_est_prise_pas_la_date_de_RETOUCHE(self):
        """⚠️ Deux `<time>` cohabitent dans le meme bloc. Prendre le premier
        venu daterait la victime de sa modification (ici le 2026-10-02 au lieu
        du 2026-09-19) -- meme famille que la date d'INSCRIPTION DE L'AUTEUR
        sur Dread, qui aurait date tous les fils pareil."""
        date = self._victimes()[0].published_at
        assert date.strftime("%Y-%m-%d") == "2026-09-19"

    def test_la_categorie_leaked_vaut_PUBLISHED(self):
        victime = self._victimes()[0]
        assert victime.publication_status == PUBLISHED
        assert "LEAKED" in (victime.publication_evidence or "")

    def test_la_categorie_new_laisse_le_statut_INCONNU(self):
        """⚠️ `new` est une etiquette de FRAICHEUR, pas une declaration de
        publication. La traduire en « en attente » inventerait un fait
        affiche a l'analyste."""
        victime = self._victimes()[1]
        assert victime.publication_status is None

    def test_le_lien_de_detail_est_absolu(self):
        """Il est relatif dans la page (`/?p=813`) : sans `urljoin`, la
        completion des descriptions ne pourrait pas le requeter."""
        assert self._victimes()[0].detail_url == f"{ARCUS_URL}/?p=813"

    def test_le_volume_annonce_est_extrait(self):
        assert self._victimes()[0].volume == "80 GB"


# --------------------------------------------------------------------------
# Transverse
# --------------------------------------------------------------------------
class TestSelectionDesParsers:
    """Un marqueur d'hote trop court capterait un autre site EN SILENCE : la
    source paraitrait collectee et serait parsee avec les mauvais
    selecteurs."""

    NOUVEAUX = {
        INC_URL: parse_incransom,
        INC_BLOG_URL: parse_incransom,
        RH_URL: parse_ransomhouse,
        DEADLOCK_URL: parse_deadlock,
        ARCUS_URL: parse_arcusmedia,
    }

    def test_chaque_nouvelle_adresse_choisit_SON_parser(self):
        for url, attendu in self.NOUVEAUX.items():
            assert pick_parser(url) is attendu, url

    def test_aucun_marqueur_ne_capte_deux_adresses(self):
        """Temoin : un seul marqueur doit correspondre a chaque hote. Deux
        correspondances signifieraient qu'un marqueur est trop generique et
        que l'ordre du dictionnaire decide du parser."""
        for url in self.NOUVEAUX:
            hote = url.split("//", 1)[1].split("/")[0]
            touches = [marqueur for marqueur in _PARSERS if marqueur in hote]
            assert len(touches) == 1, f"{url} : {touches}"

    def test_un_hote_inconnu_retombe_sur_le_generique(self):
        """`None` fait retomber l'appelant sur `CyberScraperCollector` plutot
        que de parser avec des selecteurs devines."""
        assert pick_parser("http://inconnu7xk2mw7xobnyre354jxro4qeg.onion") is None
