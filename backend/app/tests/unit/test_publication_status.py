"""Tests du statut de publication (plan de credibilite, phase 2).

Aucun reseau. Chaque extrait HTML reproduit la structure REELLE relevee le
2026-09-24 sur la page entiere de chaque site -- y compris les pieges : le
gabarit « published » cache de LockBit, la classe portee par la carte elle-meme
chez DIRE WOLF, les echeances NIGHT SPIRE rangees dans un script."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.contracts.source import SourceContract, SourceType
from app.pipeline.collect import publication_status as ps
from app.pipeline.collect.dls import scraper
from app.pipeline.collect.dls.adapter import DlsCollector

MAINTENANT = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def horloge_figee(monkeypatch):
    monkeypatch.setattr(scraper, "_maintenant", lambda: MAINTENANT)


def _statuts(victimes):
    return [(v.name, v.publication_status) for v in victimes]


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------


def _lockbit(timer: str | None) -> str:
    compte = (
        f'<div class="post-timer"><div class="timer" data-timer="{timer}"></div></div>'
        if timer
        else ""
    )
    # ⚠️ Le `.post-timer-end` « published » est present sur TOUS les blocs,
    # en `d-none` : c'est un gabarit cache.
    return f"""
    <a class="post-block" href="/post/1">
      <div class="post-title">acme.com</div>{compte}
      <div class="post-timer-end d-none"> published </div>
      <div class="post-block-text">Documents internes</div>
    </a>"""


class TestLockbit:
    def test_sans_compte_a_rebours_publiee(self):
        v = scraper.parse_lockbit(_lockbit(None), "http://x/")
        assert _statuts(v) == [("acme.com", "published")]

    def test_compte_a_rebours_futur_en_attente(self):
        v = scraper.parse_lockbit(_lockbit("Jan 26, 2027 02:16:23"), "http://x/")
        assert v[0].publication_status == "pending"
        assert "2027-01-26" in v[0].publication_evidence

    def test_compte_a_rebours_echu_publiee(self):
        v = scraper.parse_lockbit(_lockbit("Jan 26, 2026 02:16:23"), "http://x/")
        assert v[0].publication_status == "published"

    def test_le_gabarit_cache_ne_suffit_pas_a_prouver(self):
        """Avec un compte a rebours futur, le « published » cache ne l'emporte
        pas : c'est un gabarit, pas un etat."""
        v = scraper.parse_lockbit(_lockbit("Jan 26, 2027 02:16:23"), "http://x/")
        assert v[0].publication_status == "pending"


NIGHTSPIRE = """
<div class="team-card"><a class="team-name" href="https://a.com">A</a>
  <span class="countdown" data-id="1"><span class="days">00</span>d</span></div>
<div class="team-card"><a class="team-name" href="https://b.com">B</a>
  <span class="countdown" data-id="2"><span class="days">00</span>d</span></div>
<div class="team-card"><a class="team-name" href="https://c.com">C</a>
  <span class="countdown" data-id="99"></span></div>
<script>const deadlines = {'1': 1758672000000, '2': 1790294400000};</script>
"""


class TestNightspire:
    def test_echeances_lues_dans_le_script(self):
        """Le HTML affiche « 00d » partout : seul le script porte l'echeance."""
        v = scraper.parse_nightspire(NIGHTSPIRE, "http://x/")
        assert _statuts(v) == [("A", "published"), ("B", "pending"), ("C", None)]


class TestDirewolf:
    @pytest.mark.parametrize(
        "classe,attendu",
        [
            ("countdown-expired", "published"),
            ("countdown-active", "pending"),
            ("", None),
        ],
    )
    def test_classe_portee_par_la_carte_elle_meme(self, classe, attendu):
        """⚠️ `div.card.countdown-active` : un `select_one` (descendants
        seulement) ne la voyait pas -- 0 statut sur 30 au premier essai."""
        html = f"""<div class="card {classe}"><h2 class="card-title"><span>Acme</span></h2>
          <div class="card-meta">Published: 2026-09-14</div></div>"""
        assert (
            scraper.parse_direwolf(html, "http://x/")[0].publication_status == attendu
        )


class TestKrybit:
    @pytest.mark.parametrize(
        "libelle,attendu",
        [("PUBLISHED", "published"), ("SOON", "pending"), ("NEGOTIATING", None)],
    )
    def test_libelle_affiche(self, libelle, attendu):
        html = f"""<div class="post-card"><div class="post-title">acme.com</div>
          <span class="post-status">{libelle}</span></div>"""
        assert scraper.parse_krybit(html, "http://x/")[0].publication_status == attendu


class TestQilinEtBeastNeMarquentQueLAttente:
    def test_qilin(self):
        html = """
        <div class="item_box"><div><a class="item_box-title" href="/1">Avec</a></div>
          <div class="d-flex timer_publicated"><span>Time till publication: </span>
          <div class="countdown-timer" data-remaining="580263">161h</div></div></div>
        <div class="item_box"><div><a class="item_box-title" href="/2">Sans</a></div></div>"""
        v = scraper.parse_qilin(html, "http://x/")
        assert _statuts(v) == [("Avec", "pending"), ("Sans", None)]

    def test_beast(self):
        html = """
        <a class="card" href="/1"><h3>Un</h3><span class="unpublished">unpublished</span></a>
        <a class="card" href="/2"><h3>Deux</h3><div class="timer">-d</div></a>
        <a class="card" href="/3"><h3>Trois</h3></a>"""
        v = scraper.parse_beast(html, "http://x/")
        assert _statuts(v) == [("Un", "pending"), ("Deux", "pending"), ("Trois", None)]


class TestMarqueursDePublication:
    def test_apt73_badge_visible(self):
        html = """
        <div class="segment"><div class="segment__text__off">a.com</div>
          <div class="segment__block published" style="display: grid;">Published</div></div>
        <div class="segment"><div class="segment__text__off">b.com</div>
          <div class="segment__block published" style="display: none;">Published</div></div>"""
        v = scraper.parse_apt73(html, "http://x/")
        assert _statuts(v) == [("a.com", "published"), ("b.com", None)]

    def test_payload(self):
        html = """
        <a class="card-link" href="/1"><div class="title">Un</div><div class="timer timer-expired"></div></a>
        <a class="card-link" href="/2"><div class="title">Deux</div><div class="timer"></div></a>"""
        v = scraper.parse_payload(html, "http://x/")
        assert _statuts(v) == [("Un", "published"), ("Deux", "pending")]

    def test_dragonforce(self):
        html = """
        <div class="publications-list__publication"><h3 class="list-publication__name">Un</h3>
          <div class="list-publication__timer-publicated"></div></div>
        <div class="publications-list__publication"><h3 class="list-publication__name">Deux</h3>
          <div class="list-publication__timer-publication"></div></div>"""
        v = scraper.parse_dragonforce(html, "http://x/")
        assert _statuts(v) == [("Un", "published"), ("Deux", "pending")]

    def test_dragonforce_compte_a_rebours_hors_du_texte(self):
        """⚠️ « Publication: 5 days 13:15:56 » change chaque seconde : dans la
        description, il recreait chaque victime en attente a chaque passe."""

        def carte(reste: str) -> str:
            return f"""<div class="publications-list__publication">
              <h3 class="list-publication__name">HEC Group</h3>
              <div class="list-publication__timer-publication">
              <span class="timer-publication__timer">Publication: {reste}</span></div></div>"""

        avant = scraper.parse_dragonforce(carte("5 days 13:15:56"), "http://x/")[0]
        apres = scraper.parse_dragonforce(carte("5 days 12:59:31"), "http://x/")[0]
        assert avant.description == apres.description
        assert avant.publication_status == apres.publication_status == "pending"

    def test_safepay(self):
        html = """
        <div class="card"><h5 class="card-title">a.com</h5><div class="published-text">Published</div></div>
        <div class="card"><h5 class="card-title">b.com</h5>
          <div class="countdown-bar" data-created="2026-09-01T00:00:00Z"></div></div>"""
        v = scraper.parse_safepay(html, "http://x/")
        assert _statuts(v) == [("a.com", "published"), ("b.com", "pending")]

    def test_orion_seul_le_badge_observe_compte(self):
        html = """
        <div class="post-card"><span class="company-name">a.com</span>
          <span class="status-badge status-published"><span class="status-text">PUBLISHED</span></span></div>
        <div class="post-card"><span class="company-name">b.com</span>
          <span class="status-badge status-other"></span></div>"""
        v = scraper.parse_orion(html, "http://x/")
        assert [s for _, s in _statuts(v)] == ["published", None]

    def test_mydata(self):
        html = """<div class="news_div"><a class="a_title" href="/b">a.com</a>
          <div class="data_published_text">The data has been published</div></div>"""
        assert (
            scraper.parse_mydata(html, "http://x/")[0].publication_status == "published"
        )

    def test_daixin(self):
        html = """
        <div class="card-body"><h4 class="card-title">Un</h4>
          <h6 class="card-subtitle"><a href="#">FULL LEAK - 100 docs</a></h6></div>
        <div class="card-body"><h4 class="card-title">Deux</h4>
          <h6 class="card-subtitle"><a href="#">17k PII</a>Expired</h6></div>
        <div class="card-body"><h4 class="card-title">Trois</h4></div>"""
        v = scraper.parse_daixin(html, "http://x/")
        assert _statuts(v) == [
            ("Un", "published"),
            ("Deux", "published"),
            ("Trois", None),
        ]


# --------------------------------------------------------------------------
# Le statut ne touche JAMAIS au content_hash
# --------------------------------------------------------------------------


def test_une_bascule_de_statut_ne_recree_pas_le_document():
    """⚠️ Piege des compteurs volatils : si le statut entrait dans `content`,
    chaque bascule creerait un nouveau document (ORION : 111 pour 12)."""
    source = SourceContract(
        id=uuid.uuid4(),
        name="DLS test",
        url="http://lockbit3753ekiocyo5epmpy6klmejchjtzddoekjlnt6.onion/",
        type=SourceType.ONION,
        active=False,
        created_at=MAINTENANT,
    )
    en_attente = DlsCollector(
        html_fetcher=lambda _u: _lockbit("Jan 26, 2027 02:16:23")
    ).collect(source)[0]
    publiee = DlsCollector(html_fetcher=lambda _u: _lockbit(None)).collect(source)[0]
    assert en_attente.content_hash == publiee.content_hash
    assert en_attente.source_meta["publication_status"] == "pending"
    assert publiee.source_meta["publication_status"] == "published"


# --------------------------------------------------------------------------
# Mise a jour d'un document existant
# --------------------------------------------------------------------------

T0, T1 = "2026-09-20T00:00:00+00:00", "2026-09-24T00:00:00+00:00"


class TestMergePublicationStatus:
    def test_bascule_enregistree_avec_l_etat_precedent(self):
        stocke = {"victim_name": "A", **ps.status_fields("pending", "compte", T0)}
        nouveau = ps.merge_publication_status(
            stocke, ps.status_fields("published", "expire", T1), T1
        )
        assert nouveau["publication_status"] == "published"
        assert nouveau["publication_previous_status"] == "pending"
        assert nouveau["publication_status_since"] == T1
        assert nouveau["victim_name"] == "A"  # le reste est conserve

    def test_meme_statut_rien_a_ecrire_et_date_conservee(self):
        stocke = ps.status_fields("published", "x", T0)
        assert (
            ps.merge_publication_status(
                stocke, ps.status_fields("published", "y", T1), T1
            )
            is None
        )

    def test_l_inconnu_n_efface_jamais_un_statut(self):
        stocke = ps.status_fields("published", "x", T0)
        assert ps.merge_publication_status(stocke, {"victim_name": "A"}, T1) is None
        assert ps.merge_publication_status(stocke, None, T1) is None

    def test_premier_statut_sur_un_document_ancien(self):
        """Documents collectes avant la phase 2 : aucun statut en base."""
        nouveau = ps.merge_publication_status(
            {"victim_name": "A"}, ps.status_fields("pending", "x", T1), T1
        )
        assert nouveau["publication_status"] == "pending"
        assert "publication_previous_status" not in nouveau

    def test_le_stocke_n_est_pas_mute_en_place(self):
        """JSONB sans MutableDict : il faut ASSIGNER un nouveau dict."""
        stocke = {"victim_name": "A"}
        ps.merge_publication_status(stocke, ps.status_fields("pending", "x", T1), T1)
        assert stocke == {"victim_name": "A"}

    def test_statut_absent_rien_a_poser(self):
        assert ps.status_fields(None, None, T1) == {}


@pytest.mark.parametrize(
    "statuts,attendu",
    [
        (["pending", "published", None], "published"),
        (["pending", None], "pending"),
        ([None, None], None),
        ([], None),
    ],
)
def test_meilleur_statut_d_une_victime(statuts, attendu):
    assert ps.best_status(statuts) == attendu


@pytest.mark.parametrize(
    "contenu,attendu",
    [
        ("Victime annoncee: a.com\n\nPUBLISHED - Acme est une societe", "published"),
        ("Victime annoncee: a.com\n\nSOON - Acme", "pending"),
        ("Victime annoncee: a.com\n\nPublished - Acme", "published"),
        ("Victime annoncee: a.com\n\nThe data has been published - Acme", "published"),
        # Le mot dans le texte libre ne compte pas : seul le libelle de tete.
        ("Victime annoncee: a.com\n\nAcme has PUBLISHED - a report", None),
        ("Victime annoncee: a.com\n\nNEGOTIATING - Acme", None),
        (None, None),
    ],
)
def test_libelle_recopie_par_nos_parsers(contenu, attendu):
    assert ps.status_from_collected_label(contenu) == attendu
