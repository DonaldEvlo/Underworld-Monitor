"""Tests du collecteur DLS (Data Leak Sites de gangs ransomware).

Aucun test ne touche le reseau : le fetcher est injecte. Le HTML reproduit la
structure REELLE relevee le 2026-08-24 sur LockBit (508 blocs `a.post-block`)
et NIGHT SPIRE (239 `div.team-card`)."""

import uuid
from datetime import datetime, timezone

import pytest

from app.contracts.source import SourceContract, SourceType
from app.pipeline.collect.dls.adapter import DlsCollectionError, DlsCollector
from app.pipeline.collect.dls.scraper import (
    is_supported_dls_url,
    neutraliser_compteurs,
    parse_dls,
    parse_dragonforce,
    parse_lockbit,
    parse_nightspire,
    pick_parser,
)

LOCKBIT_URL = "http://lockbit3753ekiocyo5epmpy6klmejchjtzddoekjlnt6.onion/"
NIGHTSPIRE_URL = "http://nspirep7orjq73k2x2fwh2mxgh74vm2now6cdbnnxjk2f.onion/"

# Structure reelle LockBit : le nom est dans `.post-title`, l'echeance dans
# `data-timer`, le corps dans `.post-block-text`.
LOCKBIT_HTML = """
<div class="wrap">
  <a class="post-block bad" href="/post/Z4TENkdajdrO2dbx">
    <div class="post-head"><div class="post-title-block">
      <div class="post-title"> acme-industries.com </div>
      <div class="post-timer"><div class="timer" data-timer="Jan 26, 2027 02:16:23">
        <div class="days"><span>0</span>D</div>
      </div></div>
    </div></div>
    <div class="post-block-body"><div class="post-block-text">
      Full internal data, 400 GB of confidential documents
    </div></div>
    <div class="views"><div class="updated-post-date">Updated: 21 Apr, 2025,&nbsp;&nbsp; 10:00 UTC</div></div>
  </a>
  <a class="post-block" href="/post/Bx9">
    <div class="post-title">victim-two.fr</div>
    <div class="post-block-text">Financial records</div>
  </a>
  <a class="post-block"><div class="nothing">pas de titre</div></a>
</div>
"""

# Structure reelle NIGHT SPIRE : `a.team-name` porte le nom ET le site web de
# la victime -- c'est ce lien que l'extraction generique ratait.
NIGHTSPIRE_HTML = """
<div class="wrap">
  <div class="team-card">
    <img class="team-img" src="https://flagcdn.com/w320/us.png"/>
    <a class="team-name" href="https://soins-exemple.weebly.com/">Exemple Personal Care, Inc</a>
    <p class="team-bio">Data is not available now.</p>
    <span class="countdown"><span class="days">00</span>d</span>
    <div>100GB</div>
  </div>
  <div class="team-card">
    <a class="team-name" href="https://example-corp.de">Example Corp GmbH</a>
    <p class="team-bio">Internal documents leaked</p>
  </div>
  <div class="team-card"><p class="team-bio">carte sans nom</p></div>
</div>
"""


def _source(url: str) -> SourceContract:
    return SourceContract(
        id=uuid.uuid4(),
        name="DLS test",
        url=url,
        type=SourceType.ONION,
        active=False,
        created_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )


class TestParserSelection:
    def test_recognises_lockbit(self):
        assert pick_parser(LOCKBIT_URL) is parse_lockbit

    def test_recognises_nightspire(self):
        assert pick_parser(NIGHTSPIRE_URL) is parse_nightspire

    def test_recognises_both_dragonforce_addresses(self):
        """DRAGON FORCE a migre le 2026-09-04 ; les deux adresses sont servies.

        ⚠️ Ne changer que l'URL en base ferait retomber la source sur le
        collecteur generique si le nouvel hote manquait ici : la collecte
        « reussirait » en rendant un blob unique au lieu de 24 victimes, sans
        aucune erreur. Ce test verrouille le mapping, pas le parsing.
        """
        assert pick_parser(DRAGONFORCE_URL) is parse_dragonforce
        assert pick_parser(DRAGONFORCE_URL_2026_09) is parse_dragonforce

    def test_unknown_dls_has_no_parser(self):
        """Un DLS non observe doit retomber sur le collecteur generique
        plutot que d'etre parse avec des selecteurs devines."""
        assert pick_parser("http://unknowngang.onion/") is None
        assert is_supported_dls_url("http://unknowngang.onion/") is False

    def test_parse_dls_returns_empty_for_unsupported(self):
        assert parse_dls(LOCKBIT_HTML, "http://unknowngang.onion/") == []


class TestLockbitParsing:
    def test_extracts_one_victim_per_block(self):
        victims = parse_lockbit(LOCKBIT_HTML, LOCKBIT_URL)
        assert [v.name for v in victims] == ["acme-industries.com", "victim-two.fr"]

    def test_ignores_block_without_title(self):
        assert len(parse_lockbit(LOCKBIT_HTML, LOCKBIT_URL)) == 2

    def test_prefers_updated_post_date_over_countdown(self):
        """Regression du 2026-08-24 : une premiere version ne lisait que
        `data-timer`, present sur 1 bloc sur 508 -- donc 1 date extraite sur
        508 victimes. La vraie date de publication est dans
        `.updated-post-date`, presente partout.

        Sans date, la fenetre `_ALERT_WINDOW_DAYS` de generate_alerts ne peut
        pas filtrer les victimes anciennes."""
        first = parse_lockbit(LOCKBIT_HTML, LOCKBIT_URL)[0]
        assert first.published_at == datetime(2025, 4, 21, tzinfo=timezone.utc)

    def test_falls_back_to_countdown_when_no_publication_date(self):
        html = """
        <a class="post-block" href="/post/x">
          <div class="post-title">pending-victim.com</div>
          <div class="timer" data-timer="Jan 26, 2027 02:16:23"></div>
        </a>
        """
        assert parse_lockbit(html, LOCKBIT_URL)[0].published_at == datetime(
            2027, 1, 26, tzinfo=timezone.utc
        )

    def test_extracts_announced_volume(self):
        assert parse_lockbit(LOCKBIT_HTML, LOCKBIT_URL)[0].volume == "400 GB"

    def test_builds_absolute_detail_url(self):
        first = parse_lockbit(LOCKBIT_HTML, LOCKBIT_URL)[0]
        assert first.detail_url.startswith(LOCKBIT_URL.rstrip("/"))

    def test_missing_timer_is_not_fatal(self):
        second = parse_lockbit(LOCKBIT_HTML, LOCKBIT_URL)[1]
        assert second.published_at is None
        assert second.name == "victim-two.fr"


class TestNightspireParsing:
    def test_extracts_victim_name_and_site(self):
        """Le site de la victime est le signal exploitable : `matching.py`
        travaille sur des domaines."""
        victims = parse_nightspire(NIGHTSPIRE_HTML, NIGHTSPIRE_URL)
        assert victims[0].name == "Exemple Personal Care, Inc"
        assert victims[0].site == "https://soins-exemple.weebly.com/"

    def test_ignores_card_without_name(self):
        assert len(parse_nightspire(NIGHTSPIRE_HTML, NIGHTSPIRE_URL)) == 2

    def test_extracts_volume_when_present(self):
        assert parse_nightspire(NIGHTSPIRE_HTML, NIGHTSPIRE_URL)[0].volume == "100GB"

    def test_second_victim_site_is_kept(self):
        assert (
            parse_nightspire(NIGHTSPIRE_HTML, NIGHTSPIRE_URL)[1].site
            == "https://example-corp.de"
        )


class TestCollectorProducesOneDocumentPerVictim:
    """Le coeur du correctif : le collecteur generique produisait UN document
    pour les 508 victimes de LockBit, donc une seule alerte possible."""

    def test_one_document_per_victim(self):
        collector = DlsCollector(html_fetcher=lambda _url: LOCKBIT_HTML)
        docs = collector.collect(_source(LOCKBIT_URL))
        assert len(docs) == 2
        assert docs[0].collector == "dls"

    def test_document_carries_title_date_and_meta(self):
        collector = DlsCollector(html_fetcher=lambda _url: LOCKBIT_HTML)
        doc = collector.collect(_source(LOCKBIT_URL))[0]
        assert doc.title == "acme-industries.com"
        assert doc.published_at == datetime(2025, 4, 21, tzinfo=timezone.utc)
        assert doc.source_meta["announced_volume"] == "400 GB"

    def test_victim_site_reaches_document_content(self):
        """C'est ce domaine que la detection doit voir."""
        collector = DlsCollector(html_fetcher=lambda _url: NIGHTSPIRE_HTML)
        docs = collector.collect(_source(NIGHTSPIRE_URL))
        assert any("soins-exemple.weebly.com" in d.content for d in docs)
        assert docs[0].source_meta["victim_site"].startswith("https://")

    def test_documents_have_distinct_urls(self):
        """Sans url distincte, la dedup par content_hash confondrait les
        victimes d'un meme site."""
        collector = DlsCollector(html_fetcher=lambda _url: NIGHTSPIRE_HTML)
        urls = [d.url for d in collector.collect(_source(NIGHTSPIRE_URL))]
        assert len(set(urls)) == len(urls)


DIREWOLF_HTML = """
<div class="articles-grid">
  <div class="card countdown-active">
    <h2 class="card-title"><span class="country-flag">GB</span><span>Exemple Cloud Accounting Limited</span></h2>
    <div class="card-meta">Published: 2026-08-21</div>
    <div class="card-summary">
      <div class="card-summary-item"><span class="card-summary-label">Company:</span><span class="card-summary-value">Exemple Cloud Accounting Limited</span></div>
      <div class="card-summary-item"><span class="card-summary-label">Website:</span><span class="card-summary-value">https://www.compta-exemple.com</span></div>
      <div class="card-summary-item"><span class="card-summary-label">Data Size:</span><span class="card-summary-value">55G</span></div>
    </div>
    <a href="/article/110">Read More</a>
  </div>
  <div class="card"><h2 class="card-title"><span>Sans site</span></h2></div>
</div>
"""

METAENCRYPTER_HTML = """
<div class="lt-card">
  <div class="lt-card-body">
    <div class="lt-card-head"><span class="lt-card-name">Coronex Corporation</span></div>
    <p class="lt-card-memo">Heating and cooling technologies, founded 1937.</p>
    <div class="lt-card-meta">
      <div class="lt-meta-row"><span class="lt-meta-key">Data size</span><span class="lt-meta-val">320 GB</span></div>
      <div class="lt-meta-row"><span class="lt-meta-key">Country</span><span class="lt-meta-val">Japan</span></div>
    </div>
  </div>
</div>
<div class="lt-card"><div class="lt-card-body">sans nom</div></div>
"""


class TestDirewolfParsing:
    """DIRE WOLF est le DLS le plus complet observe : nom, site, date et
    volume sont tous exposes en paires label/valeur."""

    def test_extracts_name_without_country_flag(self):
        from app.pipeline.collect.dls.scraper import parse_direwolf

        victims = parse_direwolf(DIREWOLF_HTML, "http://direwolfx.onion/")
        assert victims[0].name == "Exemple Cloud Accounting Limited"

    def test_extracts_site_date_and_volume(self):
        from app.pipeline.collect.dls.scraper import parse_direwolf

        first = parse_direwolf(DIREWOLF_HTML, "http://direwolfx.onion/")[0]
        assert first.site == "https://www.compta-exemple.com"
        assert first.published_at == datetime(2026, 8, 21, tzinfo=timezone.utc)
        assert first.volume == "55G"

    def test_card_without_summary_is_still_collected(self):
        """Le titre seul porte deja du signal : ne pas jeter la victime."""
        from app.pipeline.collect.dls.scraper import parse_direwolf

        victims = parse_direwolf(DIREWOLF_HTML, "http://direwolfx.onion/")
        assert len(victims) == 2
        assert victims[1].site is None


class TestMetaencrypterParsing:
    """METAENCRYPTER ne rendait AUCUN document avec le collecteur generique."""

    def test_extracts_name_and_volume(self):
        from app.pipeline.collect.dls.scraper import parse_metaencrypter

        victims = parse_metaencrypter(METAENCRYPTER_HTML, "http://metacrpt.onion/")
        assert victims[0].name == "Coronex Corporation"
        assert victims[0].volume == "320 GB"

    def test_ignores_card_without_name(self):
        from app.pipeline.collect.dls.scraper import parse_metaencrypter

        assert (
            len(parse_metaencrypter(METAENCRYPTER_HTML, "http://metacrpt.onion/")) == 1
        )


KRYBIT_HTML = """
<div class="posts">
  <div class="post-card" onclick="window.location='/blog/94e954f9fa40/'">
    <div class="post-header">
      <span class="post-status published">PUBLISHED</span>
      <span class="post-views">15,640</span>
    </div>
    <div class="post-content">
      <h3 class="post-title">www.institution-exemple.sn</h3>
      <div class="post-excerpt">La Institution Exemple du Senegal is an independent supreme audit institution.</div>
    </div>
  </div>
  <div class="post-card" onclick="window.location='/blog/ce605d864c/'">
    <div class="post-header"><span class="post-status">SOON</span></div>
    <div class="post-content"><h3 class="post-title">reseaux-exemple.com</h3>
      <div class="post-excerpt">UK-based platform. 40 GB</div></div>
  </div>
  <div class="post-card"><div class="post-content">sans titre</div></div>
</div>
"""


class TestKrybitParsing:
    """KRYBIT etait reste sur le collecteur generique parce qu'une analyse par
    liens n'avait rien trouve : son lien de detail vit dans un attribut
    `onclick`, pas dans un `href`.

    Consequence concrete : ses 74 victimes tenaient dans un blob unique, ce
    qui a masque la SEULE victime senegalaise du corpus
    (`institution-exemple.sn`) -- invisible a une recherche par titre de
    document."""

    def test_extracts_one_victim_per_card(self):
        from app.pipeline.collect.dls.scraper import parse_krybit

        victims = parse_krybit(KRYBIT_HTML, "http://krybitx.onion/")
        assert [v.name for v in victims] == [
            "www.institution-exemple.sn",
            "reseaux-exemple.com",
        ]

    def test_title_is_promoted_to_site(self):
        """Le titre EST un domaine sur ce site : le remonter en `site` permet
        a extract_mentioned_urls de le voir."""
        from app.pipeline.collect.dls.scraper import parse_krybit

        first = parse_krybit(KRYBIT_HTML, "http://krybitx.onion/")[0]
        assert first.site == "http://www.institution-exemple.sn"

    def test_extracts_detail_url_from_onclick(self):
        from app.pipeline.collect.dls.scraper import parse_krybit

        first = parse_krybit(KRYBIT_HTML, "http://krybitx.onion/")[0]
        assert first.detail_url == "http://krybitx.onion/blog/94e954f9fa40/"

    def test_status_is_kept_in_description(self):
        from app.pipeline.collect.dls.scraper import parse_krybit

        victims = parse_krybit(KRYBIT_HTML, "http://krybitx.onion/")
        assert victims[0].description.startswith("PUBLISHED")
        assert victims[1].description.startswith("SOON")

    def test_ignores_card_without_title(self):
        from app.pipeline.collect.dls.scraper import parse_krybit

        assert len(parse_krybit(KRYBIT_HTML, "http://krybitx.onion/")) == 2


class TestCollectorRobustness:
    """Une collecte sans resultat doit DIRE POURQUOI.

    ⚠️ Ces tests exigeaient auparavant une liste vide. Mesure du 2026-09-04 :
    l'analyste voyait alors « source injoignable ou vide » pour trois causes
    aux suites opposees -- DRAGON FORCE avait demenage (corrige en une minute),
    XSSF exigeait un CAPTCHA (non contournable), une structure modifiee demande
    un correctif de code. L'echec reste NON FATAL (exception typee, captee par
    `collect_service`), mais il est desormais motive.
    """

    def test_fetch_failure_carries_reason(self):
        def _boom(_url):
            raise RuntimeError("tor down")

        with pytest.raises(DlsCollectionError, match="injoignable"):
            DlsCollector(html_fetcher=_boom).collect(_source(LOCKBIT_URL))

    def test_empty_html_carries_reason(self):
        with pytest.raises(DlsCollectionError, match="injoignable"):
            DlsCollector(html_fetcher=lambda _u: "").collect(_source(LOCKBIT_URL))

    def test_unsupported_source_returns_empty(self):
        """Un DLS sans parser retombe sur le collecteur generique : ce n'est
        pas un echec, il ne faut donc pas lever."""
        collector = DlsCollector(html_fetcher=lambda _u: LOCKBIT_HTML)
        assert collector.collect(_source("http://unknowngang.onion/")) == []

    @pytest.mark.parametrize("html", ["<html></html>", "<div class='team-card'></div>"])
    def test_structureless_html_reports_structure_change(self, html):
        collector = DlsCollector(html_fetcher=lambda _u: html)
        with pytest.raises(DlsCollectionError, match="structure"):
            collector.collect(_source(NIGHTSPIRE_URL))

    def test_captcha_page_is_named_as_such(self):
        """Cas XSSF. Reconnaitre un anti-bot sert a l'ANNONCER et a s'arreter,
        jamais a le contourner (regle 1)."""
        page = (
            "<title>XSSF FORUM - Access Verification</title>"
            "<p>Please complete the CAPTCHA below to access the forum.</p>"
        )
        with pytest.raises(DlsCollectionError, match="anti-bot"):
            DlsCollector(html_fetcher=lambda _u: page).collect(_source(LOCKBIT_URL))

    def test_migration_notice_names_the_new_address(self):
        """Cas DRAGON FORCE : le site repondait parfaitement et annoncait sa
        nouvelle adresse -- l'information la plus utile du diagnostic."""
        nouvelle = "xjhmtitnrdrgzw4vmsghirdoo2fk35a3tzj4enlmah4pvehdspydsiyd.onion"
        page = (
            "<title>DragonForce | Migration completed</title>"
            f"<p>Blog is available now - {nouvelle}</p>"
        )
        with pytest.raises(DlsCollectionError) as leve:
            DlsCollector(html_fetcher=lambda _u: page).collect(_source(LOCKBIT_URL))
        assert nouvelle in str(leve.value)


# --- Structures reelles relevees le 2026-08-25 sur les 7 DLS qui etaient
# restes sur le collecteur generique. --------------------------------------

DRAGONFORCE_URL = (
    "http://z3wqggtxft7id3ibr7srivv5gjof5fwg76slewnzwwakjuf3nlhukdid.onion/"
)
# Adresse en service depuis le 2026-09-04 (migration annoncee et signee PGP
# sur l'ancienne). Meme structure de page, meme parser.
DRAGONFORCE_URL_2026_09 = (
    "http://xjhmtitnrdrgzw4vmsghirdoo2fk35a3tzj4enlmah4pvehdspydsiyd.onion/"
)
SAFEPAY_URL = "http://safepaypfxntwixwjrlcscft433ggemlhgkkdupi2ynhtcmvdgubmoyd.onion/"
ORION_URL = "http://cjfntkj5qeizxowuy3srceg7zo6namc3kfeor7pfn6bpdkl3w265ooid.onion/"
MYDATA_URL = (
    "http://mydatae2d63il5oaxxangwnid5loq2qmtsol2ozr6vtb7yfm5ypzo6id.onion/blog"
)
DAIXIN_URL = "http://7ukmkdtyxdkdivtjad57klqnd3kdsmq6tp45rrsxqnu76zzv3jvitlqd.onion/"
PEAR_URL = "http://peargxn3oki34c4savcbcfqofjjwjnnyrlrbszfv6ujlx36mhrh57did.onion/"
CMD_URL = "http://cmdnkiqjije2tllr3biee2sjgj3i4robg2cbtilbnytdhh2wy3syrlyd.onion"

DRAGONFORCE_HTML = """
<div class="publications-list">
  <div class="publications-list__publication" data-v-b4c5baa2>
    <div class="publication-wrapper" data-v-b4c5baa2>
      <div class="publication-top" data-v-b4c5baa2>
        <p class="list-publication__website" data-v-b4c5baa2>www.criblage-exemple.com.ar</p>
        <h3 class="list-publication__name" data-v-b4c5baa2>Criblage Exemple</h3>
        <div class="list-publication__addictional" data-v-b4c5baa2>
          <p class="publication-addictional__row" data-v-b4c5baa2>
            <a class="addiction-row__text addictional-row__link"
               href="https://criblage-exemple.com.ar">www.criblage-exemple.com.ar</a>
          </p>
        </div>
      </div>
    </div>
  </div>
  <div class="publications-list__publication" data-v-b4c5baa2>
    <div class="publication-wrapper" data-v-b4c5baa2>
      <p class="list-publication__website" data-v-b4c5baa2>www.fabricant-exemple.com</p>
      <h3 class="list-publication__name" data-v-b4c5baa2>Frato</h3>
      <a class="addictional-row__link" href="https://fabricant-exemple.com">www.fabricant-exemple.com</a>
    </div>
  </div>
</div>
"""

# SAFEPAY : une victime publiee (published-text) et une a venir
# (countdown-bar avec data-created ET data-end).
SAFEPAY_HTML = """
<div class="row">
  <div class="card bg-dark text-light h-100">
    <div class="card-header">
      <h5 class="card-title text-center mb-0">lagegepesca.it</h5>
    </div>
    <div class="card-body"><p class="card-text">Based in Lallio, near Bergamo.</p></div>
    <div class="countdown-bar-wrapper">
      <div class="countdown-bar"
           data-created="2026-08-24T18:31:53.288739+00:00"
           data-end="2026-08-25T18:31:53.288739+00:00"
           data-post-id="12"></div>
    </div>
  </div>
  <div class="card bg-dark text-light h-100">
    <div class="card-header">
      <h5 class="card-title text-center mb-0">ferme-exemple.com</h5>
    </div>
    <div class="card-body"><p class="card-text">Headquartered in Albal, Valencia. 40 GB</p></div>
    <div class="published-text"><span class="text-success fw-bold">Published</span></div>
  </div>
</div>
"""

# ORION : bloc[0] met l'URL dans card-title, les suivants mettent le DOMAINE
# dans company-name et un simple libelle dans card-title. Les deux formes
# doivent etre couvertes.
ORION_HTML = """
<div class="row">
  <div class="card h-100 post-card">
    <div class="card-body">
      <div class="leak-card-header">
        <small class="leak-date">Jul 27, 2026</small>
        <span class="company-name">Exemple Chemicals India</span>
      </div>
      <h5 class="card-title">https://www.chimie-exemple.in</h5>
      <div class="status-badge status-published"><span class="status-text">PUBLISHED</span></div>
    </div>
  </div>
  <div class="card h-100 post-card">
    <div class="card-body">
      <div class="leak-card-header">
        <small class="leak-date">Oct 28, 2025</small>
        <span class="company-name">tracteurs-exemple.com</span>
      </div>
      <h5 class="card-title">kioti</h5>
      <div class="status-badge status-published"><span class="status-text">PUBLISHED</span></div>
    </div>
  </div>
  <div class="card h-100 post-card">
    <div class="card-body">
      <div class="leak-card-header">
        <small class="leak-date">Jan 26, 2026</small>
        <span class="company-name">Orion RAAS Group</span>
      </div>
      <h5 class="card-title">Your clicks can earn you a Lamborghini</h5>
    </div>
  </div>
</div>
"""

MYDATA_HTML = """
<div class="b_block">
  <div class="news_div">
    <div class="news_title">
      <div style="float:left;"><a class="a_title" href="blog_1-30">https://www.metallurgie-exemple.com</a></div>
      <div style="float:right;"><div class="data_published_text">The data has been published</div></div>
    </div>
    <div style="line-height:20px; padding-top:5px;">
      EXEMPLE METALLOURGIA S.A.<br/>Producer of household electrical appliances.
    </div>
  </div>
  <div class="news_div">
    <div class="news_title">
      <div style="float:left;"><a class="a_title" href="blog_1-28">www.bew.co.th</a></div>
    </div>
    <div style="line-height:20px; padding-top:5px;">
      Exemple Wings Co.,Ltd.<br/>Stamping process
    </div>
  </div>
</div>
"""

# DAIXIN : un bloc victime (avec "Web Site:") et un bloc annonce generique
# (sans site) -- le second doit etre garde mais sans `site`.
DAIXIN_HTML = """
<div class="row">
  <div class="border border-warning card-body shadow-lg">
    <h4 class="border-danger card-title text-start text-white">Insurance Office of Example (US)</h4>
    <h6 class="card-subtitle mb-2 text-muted text-start">Web Site:<a href="https://assureur-exemple.com/">https://assureur-exemple.com/</a></h6>
    <p class="card-text text-start text-white">A premier full-service insurance agency. 300 GB</p>
  </div>
  <div class="border border-warning card-body shadow-lg">
    <h4 class="border-danger card-title text-start text-white">A little gift of exclusive data for everyone</h4>
    <h6 class="card-subtitle mb-2 text-muted text-start"><a href="http://htz6.onion/data/gift1/">17k PII PHI</a>Expired</h6>
  </div>
</div>
"""

# PEAR : mailing HTML. Le nom vit dans l'`id` de la checkbox, la date au
# format US mois/jour/annee.
PEAR_HTML = """
<table class="es-left">
  <tr><td class="es-text-7589">
    <div class="info">
      <input class="info__switch" id="mgrlaw" type="checkbox"/>
      <label class="info__headline" for="mgrlaw"><p><strong>Show more</strong></p></label>
      <div class="info__body">
        <p><strong>Date Company Notified:</strong> 08/20/2026</p>
        <p><strong>Site:</strong> <strong><a class="underline-one" href="http://cabinet-exemple.com">cabinet-exemple.com</a></strong></p>
      </div>
    </div>
  </td></tr>
</table>
"""

CMD_HTML = """
<div class="items">
  <div class="item-card">
    <div class="item-header">
      <img alt="Exemple Georgia" class="title-image" src="/image/3a97.jpg"/>
      <h2><a href="https://www.sante-exemple.org" rel="noopener" target="_blank">Exemple Georgia</a></h2>
    </div>
    <div class="description-before">Serving northeast Georgia since 1976. 285 GB</div>
  </div>
  <div class="item-card">
    <div class="item-header">
      <h2><a href="https://conseil-exemple.ca">Exemple &amp; Associates Inc.</a></h2>
    </div>
    <div class="description-before">Civil Enforcement Agency licensed in Alberta.</div>
  </div>
</div>
"""


class TestDragonforceParsing:
    """DRAGON FORCE etait classe "aucune structure exploitable" : l'analyse
    cherchait des liens de DETAIL, or ce site n'en expose pas depuis son
    listing. Ses 24 blocs repetitifs, eux, existaient bien."""

    def test_extracts_one_victim_per_publication(self):
        from app.pipeline.collect.dls.scraper import parse_dragonforce

        victims = parse_dragonforce(DRAGONFORCE_HTML, DRAGONFORCE_URL)
        assert [v.name for v in victims] == ["Criblage Exemple", "Frato"]

    def test_prefers_absolute_href_over_displayed_text(self):
        """Le texte affiche est `www.criblage-exemple.com.ar` (sans schema) alors que le
        href est deja absolu : c'est lui qu'on retient."""
        from app.pipeline.collect.dls.scraper import parse_dragonforce

        first = parse_dragonforce(DRAGONFORCE_HTML, DRAGONFORCE_URL)[0]
        assert first.site == "https://criblage-exemple.com.ar"


class TestSafepayParsing:
    def test_extracts_domain_from_title(self):
        from app.pipeline.collect.dls.scraper import parse_safepay

        victims = parse_safepay(SAFEPAY_HTML, SAFEPAY_URL)
        assert [v.name for v in victims] == ["lagegepesca.it", "ferme-exemple.com"]
        assert victims[0].site == "http://lagegepesca.it"

    def test_reads_data_created_not_data_end(self):
        """Piege du `data-timer` LockBit : `data-end` est une echeance de
        publication, pas une date de parution. Lire `data-end` daterait la
        victime dans le futur."""
        from app.pipeline.collect.dls.scraper import parse_safepay

        first = parse_safepay(SAFEPAY_HTML, SAFEPAY_URL)[0]
        assert first.published_at == datetime(
            2026, 8, 24, 18, 31, 53, 288739, tzinfo=timezone.utc
        )

    def test_published_victim_has_status_in_description(self):
        from app.pipeline.collect.dls.scraper import parse_safepay

        second = parse_safepay(SAFEPAY_HTML, SAFEPAY_URL)[1]
        assert second.description.startswith("Published")
        assert second.volume == "40 GB"


class TestOrionParsing:
    """⚠️ Le piege central de ce parser : `card-title` et `company-name` ne
    portent PAS la meme information d'un bloc a l'autre. Lire le seul
    premier bloc donnait 1 site sur 12."""

    def test_reads_url_from_title_when_present(self):
        from app.pipeline.collect.dls.scraper import parse_orion

        first = parse_orion(ORION_HTML, ORION_URL)[0]
        assert first.name == "Exemple Chemicals India"
        assert first.site == "https://www.chimie-exemple.in"

    def test_reads_domain_from_company_name_when_title_is_a_label(self):
        """Bloc[1] : company-name = "tracteurs-exemple.com" (le domaine),
        card-title = "kioti" (un libelle). C'est l'inverse du bloc[0]."""
        from app.pipeline.collect.dls.scraper import parse_orion

        second = parse_orion(ORION_HTML, ORION_URL)[1]
        assert second.site == "http://tracteurs-exemple.com"

    def test_gang_announcement_has_no_site(self):
        """Les annonces du gang lui-meme ne portent aucun domaine : elles ne
        doivent pas en inventer un."""
        from app.pipeline.collect.dls.scraper import parse_orion

        third = parse_orion(ORION_HTML, ORION_URL)[2]
        assert third.site is None

    def test_parses_month_name_date(self):
        from app.pipeline.collect.dls.scraper import parse_orion

        victims = parse_orion(ORION_HTML, ORION_URL)
        assert victims[0].published_at == datetime(2026, 7, 27, tzinfo=timezone.utc)
        assert victims[1].published_at == datetime(2025, 10, 28, tzinfo=timezone.utc)

    def test_compteur_de_vues_sans_libelle_ignore(self):
        """⚠️ `div.views-count` = icone + nombre, sans le mot « views » :
        recopie dans la description, il recreait la victime a chaque passe
        (16 victimes ORION, mesure du 2026-09-24)."""
        from app.pipeline.collect.dls.scraper import parse_orion

        def carte(vues: int) -> str:
            return f"""<div class="card h-100 post-card">
              <div class="views-count"><i class="bi bi-eye"></i> {vues} </div>
              <div class="card-body"><span class="company-name">acme.com</span>
              <h5 class="card-title">acme</h5></div></div>"""

        avant = parse_orion(carte(189221), ORION_URL)[0]
        apres = parse_orion(carte(191281), ORION_URL)[0]
        assert avant.description == apres.description
        assert "189221" not in (avant.description or "")


class TestMydataParsing:
    def test_company_name_comes_from_description_first_line(self):
        from app.pipeline.collect.dls.scraper import parse_mydata

        victims = parse_mydata(MYDATA_HTML, MYDATA_URL)
        assert victims[0].name == "EXEMPLE METALLOURGIA S.A."
        assert victims[1].name == "Exemple Wings Co.,Ltd."

    def test_site_is_normalised_when_schema_missing(self):
        """Le 2e lien s'ecrit `www.bew.co.th` sans schema : sans
        normalisation, extract_mentioned_urls ne le verrait pas."""
        from app.pipeline.collect.dls.scraper import parse_mydata

        assert parse_mydata(MYDATA_HTML, MYDATA_URL)[1].site == "http://www.bew.co.th"

    def test_detail_url_is_absolute(self):
        from app.pipeline.collect.dls.scraper import parse_mydata

        first = parse_mydata(MYDATA_HTML, MYDATA_URL)[0]
        assert first.detail_url.endswith("/blog_1-30")


class TestDaixinParsing:
    def test_extracts_site_from_web_site_subtitle(self):
        from app.pipeline.collect.dls.scraper import parse_daixin

        victims = parse_daixin(DAIXIN_HTML, DAIXIN_URL)
        assert victims[0].name == "Insurance Office of Example (US)"
        assert victims[0].site == "https://assureur-exemple.com/"

    def test_generic_announcement_is_kept_without_site(self):
        """Ces blocs ne sont pas des victimes nommees : les garder documente
        l'annonce, mais `site` doit rester None pour ne produire aucune
        detection `domain` trompeuse."""
        from app.pipeline.collect.dls.scraper import parse_daixin

        second = parse_daixin(DAIXIN_HTML, DAIXIN_URL)[1]
        assert second.site is None


class TestPearParsing:
    def test_name_and_site_come_from_body_link(self):
        from app.pipeline.collect.dls.scraper import parse_pear

        victims = parse_pear(PEAR_HTML, PEAR_URL)
        assert len(victims) == 1
        assert victims[0].site == "http://cabinet-exemple.com"
        assert victims[0].name == "cabinet-exemple.com"

    def test_parses_us_slash_date(self):
        """`08/20/2026` est mois/jour/annee : un 20e mois n'existe pas. Ne pas
        transposer a Dread, qui date en jour-avant-mois."""
        from app.pipeline.collect.dls.scraper import parse_pear

        assert parse_pear(PEAR_HTML, PEAR_URL)[0].published_at == datetime(
            2026, 8, 20, tzinfo=timezone.utc
        )


class TestCmdParsing:
    def test_extracts_victim_per_item_card(self):
        from app.pipeline.collect.dls.scraper import parse_cmd

        victims = parse_cmd(CMD_HTML, CMD_URL)
        assert [v.name for v in victims] == [
            "Exemple Georgia",
            "Exemple & Associates Inc.",
        ]
        assert victims[0].site == "https://www.sante-exemple.org"


class TestCmdPagination:
    """CMD n'affiche que 3 victimes sur 41 sur son accueil, sans aucun indice
    qu'il en manque 38 : un echec parfaitement silencieux."""

    def test_listing_urls_targets_items_page(self):
        from app.pipeline.collect.dls.scraper import listing_urls

        urls = listing_urls(CMD_URL)
        assert len(urls) > 1
        assert all("/items?page=" in u for u in urls)

    def test_listing_urls_keeps_server_page_size(self):
        """Le serveur IGNORE per_page et renvoie 6 quoi qu'on demande :
        `per_page=60` semblait marcher tout en perdant 35 victimes sur 41."""
        from app.pipeline.collect.dls.scraper import listing_urls

        assert all("per_page=6&" in u for u in listing_urls(CMD_URL))

    def test_other_dls_are_single_page(self):
        from app.pipeline.collect.dls.scraper import listing_urls

        assert listing_urls(LOCKBIT_URL) == [LOCKBIT_URL]

    def test_collector_stops_when_a_page_adds_nothing_new(self):
        """CMD re-sert la derniere page a l'identique au lieu d'une page vide
        (page 8 = page 7) : s'arreter sur "page vide" bouclerait jusqu'au
        plafond en rechargeant la meme page."""
        calls: list[str] = []

        def _always_same_page(url):
            calls.append(url)
            return CMD_HTML

        docs = DlsCollector(html_fetcher=_always_same_page).collect(_source(CMD_URL))
        assert len(docs) == 2
        # 1re page utile + 1 page qui n'apporte rien -> arret immediat.
        assert len(calls) == 2

    def test_collector_survives_one_failing_page(self):
        """Une page en echec ne doit pas faire perdre les autres."""
        state = {"n": 0}

        def _fail_first(url):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("tor hiccup")
            return CMD_HTML

        docs = DlsCollector(html_fetcher=_fail_first).collect(_source(CMD_URL))
        assert len(docs) == 2


class TestNewParsersAreRegistered:
    """Un parser ecrit mais non enregistre est du code mort : le site
    retomberait silencieusement sur le collecteur generique."""

    @pytest.mark.parametrize(
        "url",
        [
            DRAGONFORCE_URL,
            SAFEPAY_URL,
            ORION_URL,
            MYDATA_URL,
            DAIXIN_URL,
            PEAR_URL,
            CMD_URL,
        ],
    )
    def test_url_is_supported(self, url):
        assert is_supported_dls_url(url)


class TestDetailPageCompletesTruncatedDescriptions:
    """⚠️ La liste d'un DLS n'affiche qu'un APERCU. Mesure du 2026-09-03 :
    **115 documents KRYBIT sur 115** se terminaient par des points de
    suspension, 320 sur 494 chez LOCKBIT. Le contenu stocke faisait
    199 caracteres la ou la page de la victime en contient 1788 -- neuf fois
    plus, et son URL etait connue depuis le debut.

    Le fetcher est injecte : ces tests ne touchent pas au reseau."""

    def test_a_truncated_description_is_replaced_by_the_detail_page(self):
        liste = """
            <div class="posts">
              <div class="post-card" onclick="window.location='/blog/abc/'">
                <div class="post-content">
                  <h3 class="post-title">victime.example</h3>
                  <div class="post-excerpt">Une organisation qui...</div>
                </div>
              </div>
            </div>
        """
        # ⚠️ La page de detail NOMME sa victime -- c'est le cas sur le corpus
        # reel, et depuis le 2026-09-15 `detail_page_is_about` l'exige (de
        # facon tolerante aux variantes de libelle). Une page qui ne parle pas
        # de cette victime est desormais rejetee : c'etait le defaut PAYLOAD,
        # ou la page de LISTE etait servie pour chaque victime.
        detail = (
            "<html><body><script>var x=1</script>"
            "<p>victime.example : texte complet de la page de la victime, "
            "nettement plus long que l'apercu affiche sur la liste du site, "
            "avec tous les details publies par le gang sur cette "
            "organisation.</p></body></html>"
        )

        appels: list[str] = []

        def fetcher(url: str) -> str:
            appels.append(url)
            return detail if "/blog/abc" in url else liste

        source = _source(
            "http://krybitx3fh5krdnhegyp2ob3lhizsaiadturtio3ginf7it5gsdgu2yd.onion/"
        )
        documents = DlsCollector(fetcher).collect(source)

        assert len(documents) == 1
        contenu = documents[0].content
        assert "texte complet de la page de la victime" in contenu
        # Le script est retire par l'extraction generique.
        assert "var x=1" not in contenu
        assert any("/blog/abc" in u for u in appels)

    def test_a_complete_description_triggers_no_extra_request(self):
        """Pas de requete Tor inutile : seules les descriptions tronquees
        justifient d'aller chercher la page de detail."""
        longue = "Description complete et suffisamment longue. " * 10
        liste = f"""
            <div class="posts">
              <div class="post-card" onclick="window.location='/blog/abc/'">
                <div class="post-content">
                  <h3 class="post-title">victime.example</h3>
                  <div class="post-excerpt">{longue}</div>
                </div>
              </div>
            </div>
        """
        appels: list[str] = []

        def fetcher(url: str) -> str:
            appels.append(url)
            return liste

        source = _source(
            "http://krybitx3fh5krdnhegyp2ob3lhizsaiadturtio3ginf7it5gsdgu2yd.onion/"
        )
        DlsCollector(fetcher).collect(source)
        assert not any("/blog/abc" in u for u in appels)

    def test_a_failing_detail_page_keeps_the_preview(self):
        """Une description courte vaut mieux qu'une victime perdue."""
        liste = """
            <div class="posts">
              <div class="post-card" onclick="window.location='/blog/abc/'">
                <div class="post-content">
                  <h3 class="post-title">victime.example</h3>
                  <div class="post-excerpt">Apercu tronque...</div>
                </div>
              </div>
            </div>
        """

        def fetcher(url: str) -> str:
            if "/blog/abc" in url:
                raise RuntimeError("onion injoignable")
            return liste

        source = _source(
            "http://krybitx3fh5krdnhegyp2ob3lhizsaiadturtio3ginf7it5gsdgu2yd.onion/"
        )
        documents = DlsCollector(fetcher).collect(source)
        assert len(documents) == 1
        assert "Apercu tronque" in documents[0].content


class TestCompteursVolatils:
    """Un compteur de vues dans la carte fait echouer la deduplication.

    ⚠️ Mesure du 2026-09-04 : ORION avait 111 documents en base pour 12
    victimes reelles (x9,2), QILIN x2,0, KRYBIT x1,6. Le `content_hash`
    changeait a chaque consultation parce que le nombre de vues changeait --
    aucune erreur, aucun signal, la source paraissait simplement productive.
    """

    def test_meme_carte_deux_consultations_donne_le_meme_texte(self):
        avant = neutraliser_compteurs(
            "transitaire-exemple.com PUBLISHED Access Hidden Content 188679 views"
        )
        apres = neutraliser_compteurs(
            "transitaire-exemple.com PUBLISHED Access Hidden Content 189283 views"
        )
        assert avant == apres

    def test_krybit_vues_majuscules_et_compte_a_rebours(self):
        avant = neutraliser_compteurs("STATISTICS 79437 VIEWS 0 IMAGES 00m 00s")
        apres = neutraliser_compteurs("STATISTICS 79512 VIEWS 0 IMAGES 12m 45s")
        assert avant == apres

    def test_qilin_compteur_sans_etiquette_propre(self):
        """QILIN ecrit « <vues> <images> photos » : le premier nombre ne se
        reconnait qu'a sa position, pas a une etiquette."""
        avant = neutraliser_compteurs("Company url Aug 30, 2026 5220 0 photos")
        apres = neutraliser_compteurs("Company url Aug 30, 2026 5244 0 photos")
        assert avant == apres
        # La date, elle, doit survivre : c'est du renseignement.
        assert "Aug 30, 2026" in avant

    def test_comptes_a_rebours_des_deux_formats(self):
        """Residu mesure le 2026-09-04 apres un premier correctif : QILIN et
        KRYBIT restaient instables a cause de leur DECOMPTE, pas de leurs vues.
        Chacun l'ecrit differemment."""
        qilin_a = neutraliser_compteurs("Time till publication: 43h : 36m // IMAGES")
        qilin_b = neutraliser_compteurs("Time till publication: 43h : 33m // IMAGES")
        assert qilin_a == qilin_b

        krybit_a = neutraliser_compteurs("construction-exemple.com 32h 00m 00s n views")
        krybit_b = neutraliser_compteurs("construction-exemple.com 31h 12m 47s n views")
        assert krybit_a == krybit_b

    def test_une_seule_unite_de_duree_est_conservee(self):
        """⚠️ Garde-fou : deux unites au minimum. « 500 m » ou « 3 j » isoles
        appartiennent au texte de la victime, les effacer detruirait du sens."""
        texte = "Usine de 500 m2, activite suspendue 3 j"
        assert neutraliser_compteurs(texte) == texte

    def test_le_volume_annonce_est_preserve(self):
        """⚠️ Le garde-fou du correctif : retirer trop de nombres detruirait le
        signal. Un volume est ce qui qualifie une fuite."""
        texte = "Full internal data, 400 GB of confidential documents, 12000 views"
        assert "400 GB" in neutraliser_compteurs(texte)

    def test_domaine_et_nom_intacts(self):
        texte = "automotores-exemple.com.ar 26049 VIEWS"
        assert "automotores-exemple.com.ar" in neutraliser_compteurs(texte)

    def test_texte_sans_compteur_inchange(self):
        texte = "Victime annoncee: Acme Corp\nSite: https://acme.com"
        assert neutraliser_compteurs(texte) == texte

    def test_document_construit_est_stable_entre_deux_collectes(self):
        """Le vrai critere : deux collectes successives doivent produire un
        contenu identique, donc le meme `content_hash`, donc zero doublon."""
        gabarit = (
            '<div class="post-card"><h2 class="post-title">victime-x.com</h2>'
            '<div class="post-status">PUBLISHED</div>'
            '<p class="post-desc">Leak complet {n} VIEWS 0 IMAGES</p></div>'
        )
        premiere = DlsCollector(html_fetcher=lambda _u: gabarit.format(n=1000))
        seconde = DlsCollector(html_fetcher=lambda _u: gabarit.format(n=9999))
        source = _source("http://krybitx.onion/")
        a = premiere.collect(source)
        b = seconde.collect(source)
        assert a and b
        assert a[0].content == b[0].content


class TestApt73LienDansOnclick:
    """⚠️ MEME PIEGE QUE KRYBIT : le lien de detail vit dans un `onclick`.

    Mesure du 2026-09-04 : **112 documents APT73 sur 132** restaient tronques
    (« ...provides insurance (aut... ») parce que le parser ne trouvait aucun
    `detail_url` -- il cherchait un `href`. Le lien existait depuis le debut :
    `onclick="window.location.href='/page_company.php?id=161'"`.

    Chercher un `href` n'est pas chercher une structure.
    """

    HTML = (
        "<div class='segment published' "
        "onclick=\"window.location.href='/page_company.php?id=161'\">"
        "<div class='segment__text__off'>prevoyance-exemple.com</div>"
        "<div class='segment__text__dsc'>Provident Insurance is an insurance "
        "company in Ghana that provides insurance (aut...</div>"
        "</div>"
        # Bloc SANS onclick : doit rester exploitable, sans URL de detail.
        "<div class='segment'>"
        "<div class='segment__text__off'>sans-lien.com</div></div>"
    )
    URL = "http://bashex7mokreyoxl6wlswxl4foi7okgs7or7aergnuiockuoq35yt3ad.onion"

    def test_le_lien_onclick_devient_une_url_absolue(self):
        from app.pipeline.collect.dls.scraper import parse_apt73

        victimes = parse_apt73(self.HTML, self.URL)
        assert victimes[0].detail_url == f"{self.URL}/page_company.php?id=161"

    def test_un_bloc_sans_onclick_reste_exploitable(self):
        """L'absence de lien n'est pas une erreur : la victime compte quand
        meme, avec son apercu."""
        from app.pipeline.collect.dls.scraper import parse_apt73

        victimes = parse_apt73(self.HTML, self.URL)
        assert victimes[1].name == "sans-lien.com"
        assert victimes[1].detail_url is None

    def test_l_apercu_tronque_declenche_la_completion(self):
        """C'est la conjonction des deux qui repare le contenu coupe :
        un apercu tronque ET une URL de detail."""
        from app.pipeline.collect.dls.scraper import looks_truncated, parse_apt73

        victime = parse_apt73(self.HTML, self.URL)[0]
        assert looks_truncated(victime.description)
        assert victime.detail_url


class TestCompteurNeMangePasLesAutresValeurs:
    """⚠️ Degat collateral du nettoyage, trouve le 2026-09-04.

    « Deadline: 2026/05/15 10:00:00 UTC +0 Views: 97614 » devenait
    « UTC +n Views » : le DECALAGE HORAIRE etait avale, le « 0 » de « +0 »
    ayant ete lu comme le compteur de « Views ». Le defaut etait invisible tant
    que le contenu APT73 restait tronque -- il n'est apparu qu'une fois les
    pages de detail reellement recuperees.
    """

    def test_le_decalage_horaire_survit(self):
        texte = "Deadline: 2026/05/15 10:00:00 UTC +0 Views: 97614"
        assert "UTC +0" in neutraliser_compteurs(texte)

    def test_le_compteur_est_bien_neutralise_malgre_tout(self):
        """⚠️ Et dans les DEUX SENS. KRYBIT ecrit « 79437 VIEWS », APT73
        « Views: 97614 ». Le second n'etait pas couvert : le compteur variait
        a chaque consultation et APT73 recreait ses documents indefiniment --
        le defaut corrige sur ORION, revenu par un autre chemin des que les
        pages de detail ont ete recuperees."""
        avant = neutraliser_compteurs("UTC +0 Views: 97614")
        apres = neutraliser_compteurs("UTC +0 Views: 98002")
        assert avant == apres


class TestRotationDuBudgetDeCompletion:
    """⚠️ Sans rotation, les memes 60 victimes etaient completees a CHAQUE
    passe et les suivantes JAMAIS.

    L'apercu de la LISTE reste tronque quoi qu'on ait deja en base : le
    compteur repartait donc toujours du debut. Mesure du 2026-09-04 sur APT73 :
    deux passes successives -> **0 nouveau document**, **112 tronques figes sur
    252**. Ce n'etait pas une progression par vagues, c'etait un plafond
    definitif sur les 60 premieres.
    """

    def _victimes(self, n):
        return (
            "".join(
                f"<div class='segment' onclick=\"window.location.href='/p?id={i}'\">"
                f"<div class='segment__text__off'>v{i}.com</div>"
                f"<div class='segment__text__dsc'>apercu tronque {i}...</div></div>"
                for i in range(n)
            ),
            "http://bashex7mokreyoxl6wlswxl4foi7okgs7or7aergnuiockuoq35yt3ad.onion",
        )

    def _collecte(self, rotation):
        html, url = self._victimes(5)
        vus: list[str] = []

        def _fetch(cible):
            if cible == url:
                return html
            vus.append(cible)
            return "<html><body>texte complet et nettement plus long</body></html>"

        collecteur = DlsCollector(html_fetcher=_fetch)
        from app.pipeline.collect.dls.scraper import parse_apt73

        collecteur._completer_descriptions(parse_apt73(html, url), rotation=rotation)
        return vus

    def test_deux_passes_ne_visitent_pas_les_memes_victimes(self, monkeypatch):
        monkeypatch.setattr(
            "app.pipeline.collect.dls.adapter.DEFAULT_MAX_DETAIL_FETCHES", 2
        )
        premiere = self._collecte(rotation=0)
        seconde = self._collecte(rotation=2)
        assert premiere and seconde
        assert premiere != seconde

    def test_l_ordre_des_documents_ne_depend_pas_du_jour(self):
        """⚠️ La rotation ne concerne que l'ORDRE DE RECUPERATION. L'ordre des
        victimes rendues doit rester celui du site, sinon la liste affichee
        changerait d'un jour a l'autre sans raison."""
        html, url = self._victimes(5)
        from app.pipeline.collect.dls.scraper import parse_apt73

        victimes = parse_apt73(html, url)
        collecteur = DlsCollector(html_fetcher=lambda _u: "<html>court</html>")
        for rotation in (0, 3, 7):
            rendues = collecteur._completer_descriptions(victimes, rotation=rotation)
            assert [v.name for v in rendues] == [v.name for v in victimes]

    def test_aucune_victime_ne_fait_pas_lever(self):
        collecteur = DlsCollector(html_fetcher=lambda _u: "")
        assert collecteur._completer_descriptions([], rotation=5) == []
