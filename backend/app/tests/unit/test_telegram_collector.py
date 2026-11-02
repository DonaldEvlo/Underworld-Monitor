"""Collecteur de canaux Telegram publics (apercu web) -- logique pure.

Aucun reseau : le fetcher HTML est injecte. Ce qui est verrouille : le parsing
d'URL (canaux publics vs liens prives), l'extraction des messages, l'exclusion
des messages de service, et surtout l'invariant CLE -- les vues (compteur
volatil) ne sont JAMAIS dans le `content`, sinon la dedup par `content_hash`
casse (piege ORION/KRYBIT)."""

import uuid
from datetime import datetime, timezone

import pytest

from app.contracts.source import SourceContract, SourceType
from app.pipeline.collect.telegram.adapter import TelegramChannelCollector
from app.pipeline.collect.telegram.scraper import (
    channel_from_url,
    is_telegram_url,
    parse_channel_messages,
    preview_url,
)

# Fixture calquee sur la structure reelle verifiee via Tor le 2026-09-14 :
# `div.tgme_widget_message` + data-post, `.tgme_widget_message_text`, date ISO
# dans `.tgme_widget_message_date time[datetime]`, vues, et un message de
# SERVICE sans texte (a ignorer).
_HTML = """
<div class="tgme_widget_message" data-post="leakwatch/441">
  <div class="tgme_widget_message_author"><span class="tgme_widget_message_author_name">LeakWatch</span></div>
  <div class="tgme_widget_message_text">Acme Corp database leaked<br>120 GB · acme.com</div>
  <div class="tgme_widget_message_footer">
    <div class="tgme_widget_message_info">
      <span class="tgme_widget_message_views">1.43M</span>
      <a class="tgme_widget_message_date"><time datetime="2026-09-14T10:15:00+00:00"></time></a>
    </div>
  </div>
</div>
<div class="tgme_widget_message tgme_widget_message_service">
  <div class="tgme_widget_message_text"></div>
</div>
<div class="tgme_widget_message" data-post="leakwatch/442">
  <div class="tgme_widget_message_text">Second post</div>
  <div class="tgme_widget_message_views">12.3K</div>
  <a class="tgme_widget_message_date"><time datetime="2026-09-14T11:00:00+00:00"></time></a>
</div>
"""


def _source(url: str) -> SourceContract:
    return SourceContract(
        id=uuid.uuid4(),
        name="canal",
        type=SourceType.TELEGRAM,
        url=url,
        created_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
    )


class TestUrlParsing:
    @pytest.mark.parametrize(
        "url",
        [
            "https://t.me/leakwatch",
            "https://t.me/s/leakwatch",
            "https://t.me/leakwatch/441",
            "https://t.me/@leakwatch",
            "https://telegram.me/leakwatch",
            "http://www.t.me/leakwatch",
        ],
    )
    def test_channel_extracted(self, url):
        assert channel_from_url(url) == "leakwatch"

    @pytest.mark.parametrize(
        "url",
        [
            "https://t.me/+AbCdEf123",  # lien d'invitation vers un canal prive
            "https://t.me/joinchat/AbCdEf",  # idem, forme historique
            "https://t.me/c/123456/78",  # canal prive par identifiant
            "https://t.me/s",  # prefixe d'apercu sans canal
            "https://example.com/leakwatch",  # pas un hote Telegram
            "https://t.me/ab",  # trop court pour un username
        ],
    )
    def test_non_public_channel_is_none(self, url):
        assert channel_from_url(url) is None

    def test_is_telegram_url(self):
        assert is_telegram_url("https://t.me/x") is True
        assert is_telegram_url("https://telegram.me/x") is True
        assert is_telegram_url("https://t.me.evil.com/x") is False

    def test_preview_url(self):
        assert preview_url("leakwatch") == "https://t.me/s/leakwatch"


class TestParsing:
    def test_extracts_messages_with_permalink_and_date(self):
        posts = parse_channel_messages(_HTML, "leakwatch")
        assert [p.message_id for p in posts] == [441, 442]
        first = posts[0]
        assert first.url == "https://t.me/leakwatch/441"
        assert first.author == "LeakWatch"
        assert first.published_at == datetime(2026, 9, 14, 10, 15, tzinfo=timezone.utc)
        # `<br>` -> saut de ligne, texte propre.
        assert first.text == "Acme Corp database leaked\n120 GB · acme.com"

    def test_service_message_without_text_is_skipped(self):
        posts = parse_channel_messages(_HTML, "leakwatch")
        assert all(p.text for p in posts)
        assert len(posts) == 2  # le message de service n'est pas compte

    def test_views_are_captured_but_kept_out_of_text(self):
        posts = parse_channel_messages(_HTML, "leakwatch")
        assert posts[0].views == "1.43M"
        # La valeur des vues ne doit PAS apparaitre dans le texte.
        assert "1.43M" not in posts[0].text


class TestCollector:
    def test_builds_one_document_per_message(self):
        collector = TelegramChannelCollector(html_fetcher=lambda _url: _HTML)
        docs = collector.collect(_source("https://t.me/leakwatch"))
        assert len(docs) == 2
        assert all(d.collector == "telegram" for d in docs)
        assert docs[0].url == "https://t.me/leakwatch/441"
        assert docs[0].published_at == datetime(
            2026, 9, 14, 10, 15, tzinfo=timezone.utc
        )
        assert docs[0].source_meta["channel"] == "leakwatch"
        assert docs[0].source_meta["message_id"] == 441

    def test_views_never_enter_content_or_hash(self):
        """Invariant anti-piege : les vues (volatiles) restent hors du
        `content` et du `content_hash`. Deux collectes ou seules les vues
        changent doivent produire le MEME hash."""
        html_a = _HTML.replace("1.43M", "1.43M")  # vues d'aujourd'hui
        html_b = _HTML.replace("1.43M", "2.10M")  # vues de demain, texte inchange
        doc_a = TelegramChannelCollector(html_fetcher=lambda _u: html_a).collect(
            _source("https://t.me/leakwatch")
        )[0]
        doc_b = TelegramChannelCollector(html_fetcher=lambda _u: html_b).collect(
            _source("https://t.me/leakwatch")
        )[0]
        assert "1.43M" not in doc_a.content
        assert doc_a.content_hash == doc_b.content_hash
        # Les vues restent disponibles en metadonnee, distinctes.
        assert doc_a.source_meta["views"] == "1.43M"
        assert doc_b.source_meta["views"] == "2.10M"

    def test_private_invite_url_yields_no_documents(self):
        collector = TelegramChannelCollector(html_fetcher=lambda _u: _HTML)
        assert collector.collect(_source("https://t.me/+privatehash")) == []

    def test_fetch_failure_returns_empty_not_raises(self):
        def boom(_url):
            raise RuntimeError("Tor indisponible")

        collector = TelegramChannelCollector(html_fetcher=boom)
        assert collector.collect(_source("https://t.me/leakwatch")) == []
