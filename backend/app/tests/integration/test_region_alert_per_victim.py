"""Alerte regionale : une par VICTIME (migration 0032), et scission des
alertes anterieures. Base reelle isolee (transaction annulee).

Mesure qui a fonde le changement (2026-09-30) : l'alerte « Afrique » du 29/09
portait 14 victimes sous UNE gravite `medium` ; la Exemple Defence Force
(defense, attaque de moins de 30 jours, donc CRITICAL seule) y etait noyee.
"""

from __future__ import annotations

import pytest

from app.db.session import SessionLocal
from app.services.alert_service import generate_alerts
from app.tests.integration import factories as f


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _domaine(prefixe: str = "victime") -> str:
    return f"{prefixe}-{f.unique('')}.co.za"


def _victime(db, domaine: str, src=None):
    src = src or f.source(db)
    doc = f.document(db, src, title=domaine)
    return f.detection(db, doc, value_masked=domaine)


def _miennes(alertes, detections):
    ids = {d.id for d in detections}
    return [a for a in alertes if any(ad.detection_id in ids for ad in a.detections)]


class TestGeneration:
    def test_deux_victimes_deux_alertes(self, db) -> None:
        d1, d2 = _domaine("a"), _domaine("b")
        det1, det2 = _victime(db, d1), _victime(db, d2)
        db.commit()

        alertes = _miennes(generate_alerts(db, regions=["Afrique"]), [det1, det2])

        par_cle = {a.victim_key: a for a in alertes}
        assert set(par_cle) == {d1, d2}
        assert {ad.detection_id for ad in par_cle[d1].detections} == {det1.id}
        assert {ad.detection_id for ad in par_cle[d2].detections} == {det2.id}

    def test_une_victime_publiee_par_deux_sites_reste_une_alerte(self, db) -> None:
        """Deux sites, deux ecritures (`www.` ou non) : une seule organisation,
        donc une seule alerte -- la cle est celle du dedoublonnage."""
        domaine = _domaine()
        det1 = _victime(db, domaine)
        det2 = _victime(db, f"www.{domaine}")
        db.commit()

        (alerte,) = _miennes(generate_alerts(db, regions=["Afrique"]), [det1, det2])

        assert alerte.victim_key == domaine
        assert {ad.detection_id for ad in alerte.detections} == {det1.id, det2.id}


class TestAdresses:
    def test_adresse_et_domaine_d_une_organisation_une_seule_alerte(self, db) -> None:
        domaine = _domaine()
        src = f.source(db)
        doc = f.document(db, src, title=domaine)
        det_domaine = f.detection(db, doc, value_masked=domaine)
        det_adresse = f.detection(
            db, doc, type_="email", value_masked=f"c***@{domaine}"
        )
        db.commit()

        miennes = _miennes(
            generate_alerts(db, regions=["Afrique"]), [det_domaine, det_adresse]
        )

        assert [a.victim_key for a in miennes] == [domaine]
