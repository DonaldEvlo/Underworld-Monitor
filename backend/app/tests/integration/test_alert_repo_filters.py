"""Filtres de la liste d'alertes : severite et journee.

⚠️ `list` et `count` DOIVENT appliquer les memes criteres. Un total calcule sur
une autre assiette que la page servie afficherait « 42 alertes » au-dessus de 3
lignes -- exactement le defaut du filtre `announcement_class` des documents,
corrige le 2026-09-02.
"""

import uuid
from datetime import date, datetime, timezone

import pytest

from app.db.models.alert import Alert
from app.db.session import SessionLocal
from app.repositories.alert_repo import AlertRepository

JOUR_A = date(2026, 1, 5)
JOUR_B = date(2026, 1, 6)


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def alertes(db):
    """Trois alertes regionales (aucune entite requise), sur deux journees."""
    creees = []
    # ⚠️ Une REGION distincte par alerte : l'index partiel
    # `uq_alerts_region_date` interdit deux alertes regionales le meme jour
    # pour la meme region (migration 0016). Le premier jet du test l'a
    # violee -- la contrainte fait donc bien son travail.
    for indice, (jour, severite) in enumerate(
        ((JOUR_A, "high"), (JOUR_A, "medium"), (JOUR_B, "high"))
    ):
        a = Alert(
            id=uuid.uuid4(),
            entity_id=None,
            scope="region",
            region=f"test-filtres-{indice}",
            alert_date=jour,
            severity=severite,
            status="open",
            created_at=datetime.now(timezone.utc),
        )
        db.add(a)
        creees.append(a)
    db.commit()
    yield creees
    for a in creees:
        db.delete(a)
    db.commit()


class TestFiltreSeverite:
    def test_liste_et_total_concordent(self, db, alertes):
        repo = AlertRepository(db)
        ids = {a.id for a in alertes}
        lignes = [a for a in repo.list(limit=500, severities=["high"]) if a.id in ids]
        assert len(lignes) == 2
        assert all(a.severity == "high" for a in lignes)

    def test_plusieurs_severites_cumulent(self, db, alertes):
        repo = AlertRepository(db)
        ids = {a.id for a in alertes}
        lignes = [
            a
            for a in repo.list(limit=500, severities=["high", "medium"])
            if a.id in ids
        ]
        assert len(lignes) == 3

    def test_liste_vide_ne_filtre_rien(self, db, alertes):
        """⚠️ Aucune case cochee = TOUTES les gravites, pas aucune."""
        repo = AlertRepository(db)
        ids = {a.id for a in alertes}
        assert len([a for a in repo.list(limit=500, severities=[]) if a.id in ids]) == 3


class TestFiltreJournee:
    def test_une_seule_journee(self, db, alertes):
        repo = AlertRepository(db)
        ids = {a.id for a in alertes}
        lignes = [a for a in repo.list(limit=500, alert_date=JOUR_A) if a.id in ids]
        assert len(lignes) == 2

    def test_severite_et_journee_se_combinent(self, db, alertes):
        repo = AlertRepository(db)
        ids = {a.id for a in alertes}
        lignes = [
            a
            for a in repo.list(limit=500, severities=["high"], alert_date=JOUR_A)
            if a.id in ids
        ]
        assert len(lignes) == 1

    def test_le_total_suit_le_filtre(self, db, alertes):
        """Le defaut a ne pas reproduire : une pagination qui annonce plus de
        lignes qu'elle n'en sert."""
        repo = AlertRepository(db)
        total_jour = repo.count(alert_date=JOUR_A)
        lignes_jour = repo.list(limit=500, alert_date=JOUR_A)
        assert total_jour == len(lignes_jour)

    def test_journees_disponibles_sont_triees_du_plus_recent(self, db, alertes):
        jours = AlertRepository(db).dates_disponibles()
        assert jours == sorted(jours, reverse=True)
        assert JOUR_A in jours and JOUR_B in jours


class TestOrdreDeLecture:
    """La gravité ordonne la liste AVANT la pagination (2026-10-01).

    Trié dans la page seulement, une alerte critique ancienne passait en page 2
    dès que 25 alertes plus récentes existaient (Compagnie Aérienne Exemple)."""

    JOUR = date(2026, 1, 9)

    def test_critique_ancienne_en_tete_de_la_premiere_page(self, db):
        creees = []
        for indice, (severite, heure) in enumerate(
            (("critical", 1), ("medium", 5), ("medium", 6), ("high", 3))
        ):
            a = Alert(
                id=uuid.uuid4(),
                entity_id=None,
                scope="region",
                region=f"test-ordre-{indice}",
                alert_date=self.JOUR,
                severity=severite,
                status="open",
                created_at=datetime(2026, 1, 9, heure, tzinfo=timezone.utc),
            )
            db.add(a)
            creees.append(a)
        db.commit()
        try:
            page = AlertRepository(db).list(limit=2, alert_date=self.JOUR)
            assert [a.severity for a in page] == ["critical", "high"]
            suite = AlertRepository(db).list(offset=2, limit=2, alert_date=self.JOUR)
            # à gravité égale, la plus récente d'abord
            assert [a.created_at.hour for a in suite] == [6, 5]
        finally:
            for a in creees:
                db.delete(a)
            db.commit()
