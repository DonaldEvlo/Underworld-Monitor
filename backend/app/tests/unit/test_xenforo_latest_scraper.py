from app.pipeline.collect.xenforo_latest.scraper import (
    find_next_page_url,
    parse_first_post_body,
    parse_struct_items,
)

BASE_URL = "http://example.onion/whats-new/posts/"

# Markup natif "whats-new" (ex: BFD Forum) -- auteur en attribut data-author
HTML_NATIVE = """
<html><head><link rel="next" href="/whats-new/posts/123/page-2"></head>
<body>
<div class="structItem structItem--thread" data-author="SomeAuthor">
  <div class="structItem-cell structItem-cell--main">
    <div class="structItem-title">
      <a data-tp-primary="on" href="/threads/some-thread.456/">Some Thread Title</a>
    </div>
    <ul class="structItem-parts">
      <li class="structItem-startDate">
        <a href="/threads/some-thread.456/"><time class="u-dt" data-time="1700000000">Nov 14, 2023</time></a>
      </li>
      <li><a href="/forums/hacking.88/">Hacking</a></li>
    </ul>
  </div>
</div>
</body></html>
"""

# Markup addon tiers "LFS" (ex: DARKNET ARMY) -- data-date directement sur
# l'item ; auteur en <span class="username"> imbrique (PAS un <a>), confirme
# sur le markup reel : <span class="username ..."><span class="username"
# data-user-id="...">Pseudo</span></span>
HTML_ADDON = """
<html><head><link rel="next" href="/lfs/tab/?tab_id=latest_posts&page=2"></head>
<body>
<li class="structItem structItem--lfsItem" data-date="1710000000">
  <div class="structItem-cell structItem-cell--title">
    <a data-tp-primary="on" href="/threads/other-thread.789/">Other Thread Title</a>
  </div>
  <div class="structItem-cell structItem-cell--forums">
    <span class="contentRow-minor"><a href="/forums/cracking.45/">Cracking</a></span>
  </div>
  <span class="username contentRow-minor fl-r">
    <span class="username" data-user-id="209808">OtherAuthor</span>
  </span>
</li>
</body></html>
"""

HTML_LAST_PAGE = """
<html><head></head><body>
<div class="structItem structItem--thread">
  <div class="structItem-title"><a data-tp-primary="on" href="/threads/x.1/">X</a></div>
</div>
</body></html>
"""

# Page de fil (thread) : plusieurs .message, le premier est celui a extraire.
HTML_THREAD_PAGE = """
<html><body>
<article class="message message--post">
  <div class="message-content">
    <div class="bbWrapper">
      This is the real content of the first post, explaining what's inside.
    </div>
  </div>
</article>
<article class="message message--post">
  <div class="message-content">
    <div class="bbWrapper">This is a reply, should NOT be picked up.</div>
  </div>
</article>
</body></html>
"""

HTML_THREAD_PAGE_NO_MESSAGE = "<html><body><p>Page vide ou inattendue</p></body></html>"


class TestParseStructItems:
    def test_parses_native_whats_new_markup(self):
        posts = parse_struct_items(HTML_NATIVE, BASE_URL)
        assert len(posts) == 1
        post = posts[0]
        assert post.title == "Some Thread Title"
        assert post.thread_url == "http://example.onion/threads/some-thread.456/"
        assert post.forum_name == "Hacking"
        assert post.timestamp == 1700000000
        assert post.author == "SomeAuthor"

    def test_parses_third_party_addon_markup(self):
        posts = parse_struct_items(HTML_ADDON, BASE_URL)
        assert len(posts) == 1
        post = posts[0]
        assert post.title == "Other Thread Title"
        assert post.forum_name == "Cracking"
        assert post.timestamp == 1710000000
        assert post.author == "OtherAuthor"

    def test_skips_items_without_primary_link(self):
        html_no_link = '<div class="structItem"></div>'
        assert parse_struct_items(html_no_link, BASE_URL) == []


class TestFindNextPageUrl:
    def test_finds_rel_next_link(self):
        url = find_next_page_url(HTML_NATIVE, BASE_URL)
        assert url == "http://example.onion/whats-new/posts/123/page-2"

    def test_resolves_relative_url_against_current_page(self):
        url = find_next_page_url(
            HTML_ADDON, "http://example.onion/lfs/tab/?tab_id=latest_posts&page=1"
        )
        assert url == "http://example.onion/lfs/tab/?tab_id=latest_posts&page=2"

    def test_none_on_last_page(self):
        assert find_next_page_url(HTML_LAST_PAGE, BASE_URL) is None


class TestParseFirstPostBody:
    def test_extracts_only_the_first_message(self):
        body = parse_first_post_body(HTML_THREAD_PAGE)
        assert (
            body
            == "This is the real content of the first post, explaining what's inside."
        )
        assert "should NOT be picked up" not in (body or "")

    def test_none_when_no_message_found(self):
        assert parse_first_post_body(HTML_THREAD_PAGE_NO_MESSAGE) is None


class TestKnownXenForoHosts:
    """Le mapping hote -> chemin du flux est le seul bout specifique a chaque
    site : une erreur ici ne leve aucune exception, elle produit un blob."""

    def test_new_darknet_army_address_is_registered(self):
        """L'adresse historique (dna777...) echoue 3/3 essais depuis le
        2026-08-25 ; la nouvelle repond. Sans cette entree, basculer l'URL en
        base ferait retomber la source sur le collecteur generique."""
        from app.pipeline.collect.xenforo_latest.adapter import is_known_xenforo_url

        assert is_known_xenforo_url(
            "http://darknet77vonbqeatfsnawm5jtnoci5z22mxay6cizmoucgmz52mwyad.onion"
        )

    def test_both_darknet_army_addresses_are_kept(self):
        """On garde l'ancienne : un .onion peut revenir, et la retirer
        perdrait le chemin specifique qu'elle utilise."""
        from app.pipeline.collect.xenforo_latest.adapter import (
            LATEST_POSTS_PATH_BY_HOST,
        )

        hosts = list(LATEST_POSTS_PATH_BY_HOST)
        assert any(h.startswith("dna777") for h in hosts)
        assert any(h.startswith("darknet77von") for h in hosts)

    def test_mirrors_do_not_share_the_same_feed_path(self):
        """⚠️ Les deux adresses DARKNET ARMY n'exposent PAS le meme chemin :
        `/lfs/tab/...` renvoie HTTP 200 sur la nouvelle mais avec 0 bloc et
        0 titre -- un blob silencieux. Verifier le chemin de chaque miroir,
        ne jamais le supposer identique."""
        from app.pipeline.collect.xenforo_latest.adapter import (
            LATEST_POSTS_PATH_BY_HOST,
        )

        old = next(
            p for h, p in LATEST_POSTS_PATH_BY_HOST.items() if h.startswith("dna777")
        )
        new = next(
            p
            for h, p in LATEST_POSTS_PATH_BY_HOST.items()
            if h.startswith("darknet77von")
        )
        assert old != new
        assert new == "/whats-new/posts/"

    def test_start_url_uses_the_host_specific_path(self):
        from app.pipeline.collect.xenforo_latest.adapter import _start_url_for

        url = _start_url_for(
            "http://darknet77vonbqeatfsnawm5jtnoci5z22mxay6cizmoucgmz52mwyad.onion"
        )
        assert url.endswith("/whats-new/posts/")
