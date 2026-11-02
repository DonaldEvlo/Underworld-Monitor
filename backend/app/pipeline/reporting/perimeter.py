"""Le périmètre surveillé, vu par le RSSI (2026-10-05). Logique pure.

Le RSSI est le PROPRIÉTAIRE de ce périmètre : il voit ses organisations par
leur nom, leur état et la synthèse de leurs alertes. Il ne voit ni le
contenu collecté, ni les valeurs détectées, ni les adresses .onion, ni les
victimes hors périmètre : il pilote, l'analyste enquête.

⚠️ Ce module ne reçoit QUE des faits de synthèse (`OrgFact`, `AlertSynth`) :
rien ici ne peut laisser fuir une valeur détectée ou un extrait, puisqu'aucun
n'y entre. La frontière est dans la forme des données, pas dans une
discipline d'affichage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from app.pipeline.alerting.rules import CRITICAL_SECTORS
from app.pipeline.reporting.governance import SECTEURS_FR

_ORDRE = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass(frozen=True)
class OrgFact:
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    country: str | None
    sector: str | None
    active: bool
    has_selectors: bool


@dataclass(frozen=True)
class AlertSynth:
    """Une alerte au niveau de SYNTHÈSE : pas de détection, pas de preuve."""

    id: uuid.UUID
    entity_id: uuid.UUID
    alert_date: date
    severity: str
    status: str
    credibility_level: str | None
    summary: str | None
    resolution_reason: str | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None


@dataclass
class OrgState:
    org: OrgFact
    alertes: list[AlertSynth] = field(default_factory=list)

    def resume(self) -> dict:
        ouvertes = [a for a in self.alertes if a.status != "resolved"]
        par_gravite = {g: 0 for g in ("critical", "high", "medium")}
        for a in ouvertes:
            if a.severity in par_gravite:
                par_gravite[a.severity] += 1
        derniere = max(self.alertes, key=lambda a: a.alert_date, default=None)
        if not self.org.active:
            etat = "inactive"
        elif not self.org.has_selectors:
            # Angle mort : surveillée sur le papier, jamais en pratique.
            etat = "aveugle"
        elif any(a.status == "open" for a in ouvertes):
            etat = "a_traiter"
        elif ouvertes:
            etat = "en_cours"
        elif self.alertes:
            etat = "traitee"
        else:
            etat = "aucune_alerte"
        return {
            "id": str(self.org.id),
            "name": self.org.name,
            "country": self.org.country,
            "sector": self.org.sector,
            # Traduit ici : le RSSI n'a pas accès au vocabulaire des entités.
            "sector_label": (
                SECTEURS_FR.get(self.org.sector, self.org.sector)
                if self.org.sector
                else None
            ),
            "sector_critical": (self.org.sector or "") in CRITICAL_SECTORS,
            "state": etat,
            "open_by_severity": par_gravite,
            "open_total": len(ouvertes),
            "alerts_total": len(self.alertes),
            "last_alert_date": derniere.alert_date.isoformat() if derniere else None,
            "last_alert_severity": derniere.severity if derniere else None,
        }


def build_perimeter(orgs: list[OrgFact], alertes: list[AlertSynth]) -> dict:
    """Arbre groupe -> filiales. Une organisation sans parent est un groupe
    (avec ou sans filiales). Le groupe porte le CUMUL de ses filiales : c'est
    la vue du RSSI du siège. Tri : ce qui demande une action d'abord."""
    etats = {o.id: OrgState(o) for o in orgs}
    for a in alertes:
        if a.entity_id in etats:
            etats[a.entity_id].alertes.append(a)

    filiales: dict[uuid.UUID, list[OrgState]] = {}
    racines: list[OrgState] = []
    for etat in etats.values():
        parent = etat.org.parent_id
        if parent and parent in etats:
            filiales.setdefault(parent, []).append(etat)
        else:
            racines.append(etat)

    def urgence(r: dict) -> tuple:
        sev = r["open_by_severity"]
        return (-sev["critical"], -sev["high"], -r["open_total"], r["name"].lower())

    groupes = []
    for racine in racines:
        enfants = [f.resume() for f in filiales.get(racine.org.id, [])]
        enfants.sort(key=urgence)
        ligne = racine.resume()
        cumul = {g: ligne["open_by_severity"][g] for g in ligne["open_by_severity"]}
        for e in enfants:
            for g in cumul:
                cumul[g] += e["open_by_severity"][g]
        ligne["subsidiaries"] = enfants
        ligne["group_open_by_severity"] = cumul
        ligne["group_open_total"] = ligne["open_total"] + sum(
            e["open_total"] for e in enfants
        )
        groupes.append(ligne)
    groupes.sort(
        key=lambda r: (
            -r["group_open_by_severity"]["critical"],
            -r["group_open_by_severity"]["high"],
            -r["group_open_total"],
            r["name"].lower(),
        )
    )
    toutes = [r for g in groupes for r in [g, *g["subsidiaries"]]]
    return {
        "organizations": len(toutes),
        "groups_with_subsidiaries": sum(1 for g in groupes if g["subsidiaries"]),
        "to_handle": sum(1 for r in toutes if r["state"] == "a_traiter"),
        "blind": sum(1 for r in toutes if r["state"] == "aveugle"),
        "groups": groupes,
    }


def synthese_alerte(a: AlertSynth) -> dict:
    """Ce que le RSSI lit d'une alerte : gravité, crédibilité, traitement,
    résumé. Jamais les preuves."""
    return {
        "id": str(a.id),
        "alert_date": a.alert_date.isoformat(),
        "severity": a.severity,
        "status": a.status,
        "credibility_level": a.credibility_level,
        "summary": a.summary,
        "resolution_reason": a.resolution_reason,
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
    }


def trier_alertes(alertes: list[AlertSynth]) -> list[AlertSynth]:
    """Ouvertes d'abord, puis la plus grave, puis la plus récente."""
    return sorted(
        alertes,
        key=lambda a: (
            a.status == "resolved",
            _ORDRE.get(a.severity, 9),
            -a.alert_date.toordinal(),
        ),
    )
