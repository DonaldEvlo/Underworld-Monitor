"""Credibilite : qualificatifs de revendication (phase 4), sur base reelle
isolee (transaction annulee).

La logique pure est testee dans `test_credibility.py` et
`test_claim_history.py` ; ici on verifie le service : le gang de NOTRE
revendication est deduit de la source, la mesure est faite PAR VICTIME, et une
absence de mesure n'ecrit rien.

⚠️ Revue du 2026-09-30 : la premiere version rendait « douteuse » toute victime
publiee par deux gangs. Mesure faite, ce sont des republications (ORION
reprend des victimes LockBit jusqu'a trois ans apres) ou des attributions
disputees -- jamais une fuite suspecte. Le seul cas reel en base
(transitaire-exemple.com) reposait sur la revendication ORIGINALE de LockBit.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.session import SessionLocal
from app.services import credibility_service
from app.services.credibility_service import refresh_alert_credibility
from app.tests.integration import factories as f

LOCKBIT_2023 = "2023-09-16T13:02:05+00:00"
ORION_2026 = "2026-08-05T20:02:18+00:00"


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def publications(monkeypatch):
    """Remplace la lecture du cache ransomware.live : gang -> victimes
    publiees. Un gang absent = pas en cache (absence de mesure)."""
    charges: dict[str, list] = {}
    monkeypatch.setattr(
        credibility_service, "_charge_en_cache", lambda gang: charges.get(gang)
    )
    return charges


def _victime(domaine: str, discovered: str) -> dict:
    return {"victim": domaine, "domain": domaine, "discovered": discovered}


def _nom_de_source(gang: str) -> str:
    """Nom unique mais dont `gang_slug_for_source` tire le bon gang."""
    return f"{gang} ({f.unique()}) (DLS)"


def _evaluer(db, alerte):
    refresh_alert_credibility(db, alert_ids=[alerte.id])
    db.refresh(alerte)
    return alerte


class TestRepublication:
    def test_document_du_republieur_est_qualifie(self, db, publications) -> None:
        """Notre document vient du site d'ORION, qui republie une victime
        LockBit de 2023 : la preuve le dit, le niveau n'est PAS « douteuse »."""
        _, _, det, alerte = f.victime_alertee(db, source_name=_nom_de_source("ORION"))
        det.corroborated_groups = ["orion", "lockbit3"]
        db.flush()
        publications["orion"] = [_victime(det.value_masked, ORION_2026)]
        publications["lockbit3"] = [_victime(det.value_masked, LOCKBIT_2023)]

        _evaluer(db, alerte)

        assert alerte.credibility_level != "doubtful"
        assert "republication" in alerte.credibility_evidence
        assert "lockbit3 le 2023-09-16" in alerte.credibility_evidence

    def test_document_de_l_original_n_est_pas_qualifie(self, db, publications) -> None:
        """Le cas reel : notre document vient de LockBit, qui a publie en
        premier. ORION republie APRES : rien a dire sur notre revendication."""
        _, _, det, alerte = f.victime_alertee(
            db, source_name=_nom_de_source("LOCKBIT 3.0")
        )
        det.corroborated_groups = ["lockbit3", "orion"]
        db.flush()
        publications["orion"] = [_victime(det.value_masked, ORION_2026)]
        publications["lockbit3"] = [_victime(det.value_masked, LOCKBIT_2023)]

        _evaluer(db, alerte)

        assert alerte.credibility_level != "doubtful"
        assert "republication" not in alerte.credibility_evidence

    def test_historique_absent_du_cache_rien_n_est_ecrit(
        self, db, publications
    ) -> None:
        """Pas de mesure = pas de conclusion, dans un sens comme dans
        l'autre."""
        _, _, det, alerte = f.victime_alertee(db, source_name=_nom_de_source("ORION"))
        det.corroborated_groups = ["orion", "lockbit3"]
        db.flush()
        publications["orion"] = [_victime(det.value_masked, ORION_2026)]
        # lockbit3 absent du cache.

        _evaluer(db, alerte)

        assert "republication" not in alerte.credibility_evidence


class TestAttributionDisputee:
    def test_publications_contemporaines(self, db, publications) -> None:
        _, _, det, alerte = f.victime_alertee(db, source_name=_nom_de_source("BEAST"))
        det.corroborated_groups = ["beast", "qilin"]
        db.flush()
        publications["beast"] = [
            _victime(det.value_masked, "2026-09-01T10:00:00+00:00")
        ]
        publications["qilin"] = [
            _victime(det.value_masked, "2026-09-04T10:00:00+00:00")
        ]

        _evaluer(db, alerte)

        assert alerte.credibility_level != "doubtful"
        assert "attribution disputée" in alerte.credibility_evidence
        assert "qilin" in alerte.credibility_evidence


class TestMesureParVictime:
    def test_domaine_et_raison_sociale_d_un_document_un_seul_qualificatif(
        self, db, publications
    ) -> None:
        """Un site de fuite produit une detection `domain` ET une
        `organization` pour la meme victime : un seul qualificatif."""
        src = f.source(db, name=_nom_de_source("ORION"))
        domaine = f"{f.unique('victime')}.co.za"
        doc = f.document(db, src, title=domaine)
        det1 = f.detection(db, doc, value_masked=domaine)
        det2 = f.detection(db, doc, type_="organization", value_masked=domaine)
        for det in (det1, det2):
            det.corroborated_groups = ["orion", "lockbit3"]
        db.flush()
        alerte = f.alert(db, [det1, det2], ent=f.entity(db, domain=domaine))
        publications["orion"] = [_victime(domaine, ORION_2026)]
        publications["lockbit3"] = [_victime(domaine, LOCKBIT_2023)]

        _evaluer(db, alerte)

        assert alerte.credibility_evidence.count("republication :") == 1

    def test_alerte_regionale_deux_victimes_un_gang_chacune(
        self, db, publications
    ) -> None:
        """TEMOIN : une alerte regionale regroupe deux victimes revendiquees
        chacune par UN seul gang. L'agregat par alerte verrait deux gangs ;
        la mesure par victime, aucun qualificatif."""
        src = f.source(db)
        doc1 = f.document(db, src, title="domaine-exemple.co.za")
        det1 = f.detection(db, doc1, value_masked="domaine-exemple.co.za")
        det1.corroborated_groups = ["krybit"]
        doc2 = f.document(db, src, title="suivi-flotte.co.za")
        det2 = f.detection(db, doc2, value_masked="suivi-flotte.co.za")
        det2.corroborated_groups = ["direwolf"]
        db.flush()
        # Region unique : une vraie alerte « Afrique » du jour peut exister en
        # base (contrainte unique region+date).
        alerte = f.alert(db, [det1, det2], region=f.unique("Region-"))

        _evaluer(db, alerte)

        assert alerte.credibility_level != "doubtful"
        assert "republication" not in alerte.credibility_evidence
        assert "attribution disputée" not in alerte.credibility_evidence


class TestPresse:
    def test_la_presse_garde_son_niveau(self, db, publications) -> None:
        _, _, det, alerte = f.victime_alertee(db, source_name=_nom_de_source("ORION"))
        det.corroborated_groups = ["orion", "lockbit3"]
        alerte.press_confirmed_at = datetime.now(timezone.utc)
        db.flush()
        publications["orion"] = [_victime(det.value_masked, ORION_2026)]
        publications["lockbit3"] = [_victime(det.value_masked, LOCKBIT_2023)]

        _evaluer(db, alerte)

        assert alerte.credibility_level == "confirmed"
        assert "republication" in alerte.credibility_evidence
