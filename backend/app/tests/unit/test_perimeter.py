"""Périmètre surveillé vu par le RSSI -- logique pure (2026-10-05)."""

from __future__ import annotations

import uuid
from datetime import date

from app.pipeline.reporting.perimeter import (
    AlertSynth,
    OrgFact,
    build_perimeter,
    trier_alertes,
)


def _org(nom, parent=None, selecteurs=True, active=True, secteur=None):
    return OrgFact(uuid.uuid4(), nom, parent, None, secteur, active, selecteurs)


def _alerte(org, severite="medium", statut="open", jour=date(2026, 10, 1)):
    return AlertSynth(
        uuid.uuid4(), org.id, jour, severite, statut, None, None, None, None, None
    )


class TestArbre:
    def test_le_groupe_cumule_ses_filiales(self):
        groupe = _org("Groupe")
        a, b = _org("Filiale A", groupe.id), _org("Filiale B", groupe.id)
        r = build_perimeter(
            [groupe, a, b],
            [_alerte(a, "critical"), _alerte(b, "high"), _alerte(b, "high")],
        )
        ligne = r["groups"][0]
        assert ligne["group_open_by_severity"] == {
            "critical": 1,
            "high": 2,
            "medium": 0,
        }
        assert ligne["group_open_total"] == 3
        # La filiale la plus urgente en tête.
        assert [s["name"] for s in ligne["subsidiaries"]] == ["Filiale A", "Filiale B"]

    def test_le_groupe_le_plus_urgent_en_tete(self):
        calme, urgent = _org("Calme"), _org("Urgent")
        r = build_perimeter([calme, urgent], [_alerte(urgent, "critical")])
        assert [g["name"] for g in r["groups"]] == ["Urgent", "Calme"]


class TestEtats:
    def _etat(self, org, alertes=()):
        return build_perimeter([org], list(alertes))["groups"][0]["state"]

    def test_angle_mort_sans_selecteur(self):
        org = _org("Sans sélecteur", selecteurs=False)
        assert self._etat(org) == "aveugle"

    def test_a_traiter_en_cours_traitee(self):
        org = _org("Org")
        assert self._etat(org, [_alerte(org, statut="open")]) == "a_traiter"
        assert self._etat(org, [_alerte(org, statut="acknowledged")]) == "en_cours"
        assert self._etat(org, [_alerte(org, statut="resolved")]) == "traitee"
        assert self._etat(org) == "aucune_alerte"

    def test_les_resolues_ne_comptent_pas_comme_ouvertes(self):
        org = _org("Org")
        r = build_perimeter([org], [_alerte(org, "critical", "resolved")])
        assert r["groups"][0]["open_total"] == 0

    def test_secteur_nis2_signale(self):
        org = _org("Hôpital", secteur="Healthcare")
        ligne = build_perimeter([org], [])["groups"][0]
        assert ligne["sector_critical"] is True
        assert ligne["sector_label"] == "Santé"


def test_tri_ouvertes_puis_gravite_puis_fraicheur():
    org = _org("Org")
    resolue = _alerte(org, "critical", "resolved")
    vieille = _alerte(org, "high", jour=date(2026, 9, 1))
    recente = _alerte(org, "high", jour=date(2026, 10, 1))
    critique = _alerte(org, "critical")
    assert trier_alertes([resolue, vieille, recente, critique]) == [
        critique,
        recente,
        vieille,
        resolue,
    ]
