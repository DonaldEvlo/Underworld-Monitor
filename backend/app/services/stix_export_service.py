"""Export STIX 2.1 d'une alerte : base -> faits -> `pipeline/reporting/stix`.

Ce document SORT de l'outil, comme le rapport PDF : la route qui l'appelle le
journalise AVANT de le produire (regle 5). Voir la docstring de
`pipeline/reporting/stix.py` pour ce qui entre, et surtout ce qui n'entre pas
(regle 2 : aucune valeur detectee, aucun `.onion`, aucun contenu).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.alert import Alert
from app.pipeline.enrich.ttp import mitre_technique_url
from app.pipeline.reporting.stix import (
    StixAlertInput,
    StixGangProfile,
    StixTechnique,
    StixVictim,
    build_bundle,
)
from app.services.admiralty_service import rate_alerts, victim_claims
from app.services.gang_profile_service import (
    MODUS_OPERANDI_CAVEAT,
    ProfileStatus,
    modus_operandi,
)
from app.services.report_service import sujet_alerte
from app.pipeline.reporting.nommage import nom_de_fichier


def _victimes(db: Session, alerte: Alert, sujet: str) -> tuple[StixVictim, ...]:
    """Une victime par titre de document de site de fuite, avec SON gang.

    ⚠️ Pays et secteur sont portes par l'ALERTE : on ne les attribue qu'a une
    victime unique. Sur une alerte a plusieurs victimes (alertes anterieures a
    la scission), les recopier sur chacune reviendrait a inventer -- meme
    faute que « krybit revendique Suivi Flotte » (2026-09-28)."""
    paires = victim_claims(db, alerte)
    seule = len(paires) <= 1
    if not paires:
        # Annonce de forum (Organisation Exemple...) : la victime est l'entite surveillee.
        return (
            StixVictim(
                name=sujet, country=alerte.victim_country, sector=alerte.victim_sector
            ),
        )
    return tuple(
        StixVictim(
            name=titre,
            gang=gang,
            country=alerte.victim_country if seule else None,
            sector=alerte.victim_sector if seule else None,
        )
        for titre, gang in paires
    )


def _profils(db: Session, alerte: Alert) -> tuple[StixGangProfile, ...]:
    """Mode operatoire des gangs DOCUMENTES seulement : un gang injoignable ou
    sans TTP publies n'ajoute rien (absence de mesure, pas absence de
    methode -- et rien a exporter)."""
    profils = []
    for mo in modus_operandi(db, alerte):
        if mo.status is not ProfileStatus.DOCUMENTED or mo.profile is None:
            continue
        profils.append(
            StixGangProfile(
                gang=mo.gang,
                techniques=tuple(
                    StixTechnique(
                        technique_id=t.technique_id,
                        name=t.technique_name,
                        tactic=t.tactic_name or None,
                        url=mitre_technique_url(t.technique_id),
                    )
                    for t in mo.profile.techniques
                    # Un identifiant d'une forme inattendue (il vient d'un
                    # tiers) ne devient pas un objet STIX.
                    if mitre_technique_url(t.technique_id)
                ),
                tools=mo.profile.tools,
                cves=mo.profile.cves,
            )
        )
    return tuple(profils)


def _preuves(alerte: Alert) -> tuple[tuple[str, str], ...]:
    """URL CLEARNET et citables uniquement (le filtre final est dans
    `build_bundle`) : capture de l'annonce chez un agregateur, presse."""
    preuves: list[tuple[str, str]] = []
    if alerte.corroboration_evidence_url:
        preuves.append(
            ("capture de l'annonce (agregateur)", alerte.corroboration_evidence_url)
        )
    if alerte.press_source_url:
        preuves.append(("presse", alerte.press_source_url))
    if alerte.press_evidence_url:
        preuves.append(("presse (via ransomware.live)", alerte.press_evidence_url))
    return tuple(preuves)


def exporter_stix(
    db: Session, alerte: Alert, *, now: datetime | None = None
) -> tuple[dict, str]:
    """Paquet STIX 2.1 et nom de fichier propose."""
    sujet = sujet_alerte(db, alerte)
    notation = rate_alerts(db, [alerte]).get(alerte.id)
    paquet = build_bundle(
        StixAlertInput(
            alert_id=str(alerte.id),
            subject=sujet,
            created=alerte.created_at,
            modified=now or datetime.now(timezone.utc),
            severity=alerte.severity,
            victims=_victimes(db, alerte, sujet),
            credibility_level=alerte.credibility_level,
            credibility_evidence=alerte.credibility_evidence,
            admiralty=notation.code if notation else None,
            profiles=_profils(db, alerte),
            evidence=_preuves(alerte),
            modus_operandi_caveat=MODUS_OPERANDI_CAVEAT,
        )
    )
    nom = nom_de_fichier(sujet)
    return paquet, f"stix-{nom}-{alerte.alert_date.isoformat()}.json"
