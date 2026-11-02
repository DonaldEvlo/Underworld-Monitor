"""Notation Admiralty sur base reelle isolee (transaction annulee)."""

from __future__ import annotations

import pytest

from app.db.session import SessionLocal
from app.services.admiralty_service import rate_alerts, source_tracks
from app.tests.integration import factories as f


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _site_de_fuite(db, victimes: int, confirmees: int):
    """Un site de fuite avec `victimes` documents dont `confirmees`
    corrobores ; rend (source, derniere detection)."""
    src = f.source(db)
    det = None
    for i in range(victimes):
        doc = f.document(db, src)
        det = f.detection(db, doc)
        det.corroboration_status = "corroborated" if i < confirmees else "exclusive"
    db.flush()
    return src, det


class TestNotation:
    def test_historique_mesure_par_source(self, db) -> None:
        src, _ = _site_de_fuite(db, 25, 24)
        nom, historique = source_tracks(db)[src.id]
        assert (historique.evaluated, historique.corroborated) == (25, 24)
        assert historique.publishes_victims is True

    def test_alerte_de_site_fiable_publiee_et_corroboree(self, db) -> None:
        src, det = _site_de_fuite(db, 25, 25)
        ent = f.entity(db, domain=det.value_masked)
        alerte = f.alert(
            db,
            [det],
            ent=ent,
            credibility_level="published",
            corroboration_status="corroborated",
        )
        note = rate_alerts(db, [alerte])[alerte.id]
        assert note.code == "B2"
        assert note.source_name == src.name

    def test_alerte_de_forum(self, db) -> None:
        src = f.source(db, name=f.unique("FORUM "))
        det = f.detection(db, f.document(db, src, collector="mybb_latest"))
        alerte = f.alert(
            db,
            [det],
            ent=f.entity(db, domain=det.value_masked),
            credibility_level="claimed",
        )
        assert rate_alerts(db, [alerte])[alerte.id].code == "F6"

    def test_la_meilleure_source_l_emporte(self, db) -> None:
        """Une victime vue sur un forum ET sur un site fiable : la lettre est
        celle du site fiable."""
        _, det_site = _site_de_fuite(db, 25, 25)
        forum = f.source(db, name=f.unique("FORUM "))
        det_forum = f.detection(db, f.document(db, forum, collector="mybb_latest"))
        alerte = f.alert(
            db,
            [det_site, det_forum],
            ent=f.entity(db, domain="x.co.za"),
            credibility_level="published",
        )
        assert rate_alerts(db, [alerte])[alerte.id].source.valeur == "B"
