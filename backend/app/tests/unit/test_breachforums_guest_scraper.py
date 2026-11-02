from app.pipeline.collect.breachforums_guest.scraper import (
    is_breachforums_guest_url,
    parse_homepage_threads,
)

BASE_URL = "http://pwnfrm7rbf6kyerigxi677lcz5ifmoagdbqqknwdu2by27wfdst5qmqd.onion/"

HTML_HOMEPAGE = """
<html><body>
<table>
<tr>
<td class="trow1 forums__last-post">
  <div class="d-table"><div class="forums__post">
    <span class="smalltext">
      <a href="Thread-Words-for-LunarisSec?action=lastpost" title="Words for LunarisSec"><strong>Words for LunarisSec</strong></a>
      <br><span title="07-14-2026, 10:21 PM">32 minutes ago</span><br>
      by <a href="http://pwnfrm7rbf6kyerigxi677lcz5ifmoagdbqqknwdu2by27wfdst5qmqd.onion/User-pwn2ddL"><span>pwn2ddL</span></a>
    </span>
  </div></div>
</td>
</tr>
<tr>
<td class="trow2 forums__last-post">
  <div class="d-table"><div class="forums__post">
    <span class="smalltext">
      <a href="Thread-D1R-database-leak-site?action=lastpost" title="D1R: database leak site"><strong>D1R: database leak site</strong></a>
      <br><span title="07-14-2026, 09:00 PM">2 hours ago</span><br>
      by <a href="http://pwnfrm7rbf6kyerigxi677lcz5ifmoagdbqqknwdu2by27wfdst5qmqd.onion/User-someone"><span>someone</span></a>
    </span>
  </div></div>
</td>
</tr>
<tr>
<td class="trow1 forums__last-post">
  <div class="d-table"><div class="forums__post">
    <span class="smalltext">
      <a href="Thread-Words-for-LunarisSec?action=lastpost" title="Words for LunarisSec"><strong>Words for LunarisSec</strong></a>
      <br><span title="07-14-2026, 10:21 PM">32 minutes ago</span><br>
    </span>
  </div></div>
</td>
</tr>
</table>
</body></html>
"""


class TestParseHomepageThreads:
    def test_extracts_title_author_and_time(self):
        previews = parse_homepage_threads(HTML_HOMEPAGE, BASE_URL)
        assert len(previews) == 2  # dedupliqué : le 3e est un doublon du 1er
        first = previews[0]
        assert first.title == "Words for LunarisSec"
        assert (
            first.thread_url == BASE_URL + "Thread-Words-for-LunarisSec?action=lastpost"
        )
        assert first.author == "pwn2ddL"
        assert first.last_post_label == "32 minutes ago"

    def test_deduplicates_by_thread_url(self):
        previews = parse_homepage_threads(HTML_HOMEPAGE, BASE_URL)
        urls = [p.thread_url for p in previews]
        assert len(urls) == len(set(urls))

    def test_handles_missing_author_gracefully(self):
        html = """<td class="forums__last-post"><span class="smalltext">
            <a href="Thread-X" title="X Thread"><strong>X Thread</strong></a>
        </span></td>"""
        previews = parse_homepage_threads(html, BASE_URL)
        assert len(previews) == 1
        assert previews[0].author is None

    def test_empty_when_no_matching_cells(self):
        assert (
            parse_homepage_threads("<html><body>nothing here</body></html>", BASE_URL)
            == []
        )


class TestIsBreachforumsGuestUrl:
    def test_matches_known_host(self):
        assert is_breachforums_guest_url(BASE_URL)

    def test_rejects_unrelated_url(self):
        assert not is_breachforums_guest_url("http://example.onion/")
