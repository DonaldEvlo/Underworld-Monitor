"""Renseignements par victime : remplit les colonnes de la migration 0026.

Repond aux criteres de criticite qui n'avaient AUCUNE source jusqu'ici --
date reelle de l'attaque, secteur, exposition d'identifiants -- en derivant
la charge ransomware.live DEJA rapatriee par la corroboration (une seule
requete par gang et par jour, voir `corroboration_service.payload_rwl`).

⚠️ AUCUNE PII. Seuls des compteurs, des dates et des libelles sont ecrits.
La frontiere est verrouillee en amont par la FORME du contrat `VictimIntel`
(`test_victim_intel.TestAucunePII`), pas par une relecture de ce fichier.

⚠️ NE FAIT JAMAIS ECHOUER L'ALERTING. Comme la corroboration, c'est un
enrichissement : une panne reseau n'ecrit rien et laisse les colonnes en
l'etat. Le livrable est l'alerte.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.alert import Alert, AlertDetection
from app.db.models.detection import Detection
from app.db.models.entity import Entity
from app.db.models.raw_document import RawDocument
from app.pipeline.alerting.effective import effective_value
from app.services.admiralty_service import victim_claims
from app.pipeline.enrich.ransomlook_corroboration import normalise_gang
from app.pipeline.enrich.ransomware_live import (
    VictimIntel,
    parse_press_coverage,
    parse_victim_intel,
    parse_victim_intel_by_name,
    victim_name_keys,
)
from app.services.corroboration_service import payload_rwl

logger = logging.getLogger(__name__)

# ⚠️ FENETRE DE FRAICHEUR D'UN INCIDENT -- arbitrage de projet (2026-09-15).
#
# La corroboration ne dit PAS la meme chose selon l'age de l'incident :
#   - sur un incident ANCIEN, elle est une marque de VERIFIABILITE (« un tiers
#     publie la meme annonce, notre lecture est juste ») et rien de plus ;
#   - sur un incident FRAIS, qu'un agregateur l'ait deja indexe signifie que
#     la revendication s'est propagee vite -- la, c'est un facteur de risque.
#
# ⚠️ Et c'est a DOUBLE TRANCHANT, ce qui interdit d'en faire un simple
# multiplicateur : sur un incident frais, « vue par nous seuls » a aussi de la
# valeur -- nous sommes en avance, l'organisation a encore le temps d'agir.
# Ni l'un ni l'autre n'est « pire » dans l'absolu.
#
# 30 jours, et ce n'est pas arbitraire : c'est la couverture du flux
# `/api/posts` de RansomLook (mesuree le 2026-09-11), donc la definition de
# « recent » dans cet ecosysteme.
#
# MESURE SUR L'EXISTANT (2026-09-15), age reel des 32 victimes alertees :
# mediane **140 jours**, etendue 39 j -> 956 j (LockBit = incidents de 2023).
# **0 incident sous 30 jours.** La porte de fraicheur annule donc a elle seule
# l'inflation qui aurait fait passer 30 alertes sur 33 en CRITICAL : ce corpus
# est un rattrapage historique, sa corroboration est de la verifiabilite.
FENETRE_FRAICHEUR_JOURS = 30


@dataclass
class IntelOutcome:
    alerts_examined: int = 0
    alerts_updated: int = 0
    with_attack_date: int = 0
    with_credential_exposure: int = 0
    success: bool = True
    error: str | None = None


def _aware(valeur: str | None) -> datetime | None:
    """Date ISO -> datetime UTC. ⚠️ Les dates sans fuseau sont traitees comme
    UTC : le defaut qui avait fait lever `TypeError` en pleine passe de
    corroboration le 2026-09-11, trouve par la passe reelle et non par les
    tests."""
    if not valeur:
        return None
    try:
        d = datetime.fromisoformat(valeur)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def incident_is_fresh(
    attack_date: datetime | None, *, now: datetime | None = None
) -> bool:
    """True si l'incident est assez recent pour que la corroboration porte du
    RISQUE et pas seulement de la verifiabilite.

    ⚠️ Une date INCONNUE n'est pas fraiche. Supposer la fraicheur ferait
    monter en gravite tout ce qu'on ne sait pas dater -- soit 78 % du corpus
    avant cette migration. « Pas de date » n'est pas « recent »."""
    if attack_date is None:
        return False
    maintenant = now or datetime.now(timezone.utc)
    if attack_date.tzinfo is None:
        attack_date = attack_date.replace(tzinfo=timezone.utc)
    return attack_date >= maintenant - timedelta(days=FENETRE_FRAICHEUR_JOURS)


def _domaines_de_l_alerte(db: Session, alert_id) -> list[str]:
    """Valeurs de domaine rattachees a une alerte, normalisees.

    ⚠️ `value_masked` est employe sciemment : `mask_domain` laisse un domaine
    clearnet EN CLAIR (un domaine n'est pas une PII, voir detect/masking.py).
    Aucune valeur masquee n'est reconstituee."""
    lignes = db.execute(
        select(Detection.value_masked)
        .join(AlertDetection, AlertDetection.detection_id == Detection.id)
        .where(AlertDetection.alert_id == alert_id, Detection.type == "domain")
    ).all()
    return [
        v.removeprefix("www.")
        for (valeur,) in lignes
        if (v := (valeur or "").strip().lower()) and "*" not in v
    ]


def _gangs_revendicateurs(db: Session, alerte: Alert) -> list[str]:
    """Gang principal en tete, puis tous les gangs qui revendiquent les
    victimes : ceux de la corroboration ET ceux lus sur la SOURCE des
    documents (`victim_claims`, avec repli sur `source_meta.group_name`).

    ⚠️ Un document RansomLook n'est jamais corrobore -- ce serait une
    auto-confirmation. Sans cette lecture, son alerte n'avait AUCUN gang et la
    passe l'ignorait : la Exemple Defence Force (ransomhouse, Government &
    Defense, attaque du 12/09) restait sans secteur ni date, donc `medium`,
    alors qu'elle est CRITICAL (mesure du 2026-09-30)."""
    gangs = _gangs_de_l_alerte(alerte)
    for _, gang in victim_claims(db, alerte):
        if isinstance(gang, str) and gang.strip() and gang not in gangs:
            gangs.append(gang)
    return gangs


def _noms_de_l_alerte(db: Session, alert_id) -> list[str]:
    """Raisons sociales rattachees a une alerte (detections `organization`).

    Sert de repli quand aucun domaine n'est connu : une organisation
    surveillee par son seul nom (selecteur `keyword`) n'a souvent aucune
    detection `domain`. Une raison sociale n'est pas une PII."""
    lignes = db.execute(
        select(Detection.value_masked)
        .join(AlertDetection, AlertDetection.detection_id == Detection.id)
        .where(AlertDetection.alert_id == alert_id, Detection.type == "organization")
    ).all()
    noms: list[str] = []
    for (valeur,) in lignes:
        v = (valeur or "").strip()
        if v and "*" not in v and v not in noms:
            noms.append(v)
    return noms


def _par_nom(
    noms: list[str], index: dict[str, list[VictimIntel]]
) -> VictimIntel | None:
    """Renseignements d'une victime retrouvee par son NOM, ou None.

    ⚠️ Ambigu (plusieurs victimes du gang sous ce nom) = None : un secteur
    attribue a la mauvaise organisation fausserait sa gravite. Le nom complet
    est essaye avant le nom sans qualificatif (`victim_name_keys`)."""
    for nom in noms:
        for cle in victim_name_keys(nom):
            trouves = index.get(cle) or []
            if len(trouves) == 1:
                return trouves[0]
            if len(trouves) > 1:
                return None
    return None


def _domaines_declares(db: Session, alert_id) -> list[str]:
    """Domaines DECLARES par l'agregateur pour les victimes publiees par leur
    seule raison sociale (`source_meta.victim_domain`, ecrit par
    victim_location_service) -- « Exemple Defence Force » -> defense-exemple.gov.na.
    Un domaine n'est pas une PII (voir detect/masking.py)."""
    lignes = db.execute(
        select(RawDocument.source_meta)
        .join(Detection, Detection.document_id == RawDocument.id)
        .join(AlertDetection, AlertDetection.detection_id == Detection.id)
        .where(AlertDetection.alert_id == alert_id)
    ).all()
    domaines: list[str] = []
    for (meta,) in lignes:
        if not isinstance(meta, dict):
            continue
        valeur = str(meta.get("victim_domain") or "").strip().lower()
        valeur = valeur.removeprefix("www.")
        if valeur and "*" not in valeur and valeur not in domaines:
            domaines.append(valeur)
    return domaines


def _date_d_incident(domaine, trouve, intel_par_gang: dict, gangs: list[str]):
    """Date d'attaque de la victime : la PLUS ANCIENNE parmi les gangs qui la
    revendiquent, et seulement si celle du gang principal est connue.

    ⚠️ Un republieur date sinon une vieille fuite du jour de sa republication.
    Mesure du 2026-09-30 : ORION reprend des victimes LockBit jusqu'a trois ans
    apres (transitaire-exemple.com : 2023 chez LockBit, 2026 chez ORION). Si ORION
    etait le gang principal d'une alerte, la fuite de 2023 passerait pour
    « fraiche » -- donc CRITICAL dans un secteur critique.

    La regle ne fait que VIEILLIR une date connue, jamais la rajeunir : si la
    date du principal est inconnue (import en lot neutralise, absente), on
    garde None plutot que d'adopter celle d'un autre gang, qui pourrait etre
    la date du republieur. Une date fausse est pire qu'une date absente."""
    principale = _aware(trouve.attack_date)
    if principale is None:
        return None
    dates = [principale]
    for gang in gangs:
        index = intel_par_gang.get(normalise_gang(gang) or gang)
        autre = index.get(domaine) if index else None
        if autre is not None and (date := _aware(autre.attack_date)) is not None:
            dates.append(date)
    return min(dates)


def refresh_victim_intel(db: Session, *, alert_id=None) -> IntelOutcome:
    """Renseigne les colonnes de la migration 0026 sur les alertes corroborees.

    Ne traite que les alertes portant un gang : sans gang, il n'y a pas
    d'historique a interroger. Idempotent -- une seconde passe reecrit les
    memes valeurs."""
    resultat = IntelOutcome()
    # Toutes les alertes, pas seulement les corroborees : une alerte issue de
    # RansomLook n'a pas de gang corrobore, mais sa source le nomme (voir
    # `_gangs_revendicateurs`). Une alerte sans aucun gang est ignoree.
    requete = select(Alert)
    if alert_id is not None:
        requete = requete.where(Alert.id == alert_id)
    alertes = list(db.execute(requete).scalars())
    gangs_par_alerte = {a.id: _gangs_revendicateurs(db, a) for a in alertes}
    alertes = [a for a in alertes if gangs_par_alerte[a.id]]
    resultat.alerts_examined = len(alertes)
    if not alertes:
        return resultat

    # Un appel reseau par GANG, jamais par victime. TOUS les gangs qui
    # revendiquent les victimes, pas le seul principal (voir
    # `_date_d_incident`) : ce sont les memes que la passe presse qui suit,
    # donc aucun appel de plus au total.
    gangs = {g for a in alertes for g in gangs_par_alerte[a.id]}
    intel_par_gang: dict[str, dict] = {}
    noms_par_gang: dict[str, dict[str, list[VictimIntel]]] = {}
    for gang in sorted(gangs):
        try:
            charge = payload_rwl(gang)
        except Exception:
            logger.warning("Renseignements indisponibles pour %s", gang, exc_info=True)
            charge = None
        if charge is None:
            # ⚠️ Indisponible : on ne touche a RIEN pour ce gang. Ecrire des
            # zeros ferait passer « non mesure » pour « aucune exposition ».
            continue
        intel_par_gang[normalise_gang(gang) or gang] = parse_victim_intel(charge)
        noms_par_gang[normalise_gang(gang) or gang] = parse_victim_intel_by_name(charge)

    if not intel_par_gang:
        resultat.success = False
        resultat.error = "aucun historique disponible"
        return resultat

    maintenant = datetime.now(timezone.utc)
    renseignees: list = []
    for alerte in alertes:
        gangs_alerte = gangs_par_alerte[alerte.id]
        principal = gangs_alerte[0]
        index = intel_par_gang.get(normalise_gang(principal) or principal)
        if index is None:
            continue
        domaines = _domaines_de_l_alerte(db, alerte.id)
        domaines += [d for d in _domaines_declares(db, alerte.id) if d not in domaines]
        domaine, trouve = next(
            ((d, index[d]) for d in domaines if d in index),
            (None, None),
        )
        if trouve is None:
            # Repli par NOM, borne au gang principal : une organisation
            # surveillee par sa seule raison sociale n'a souvent aucun domaine
            # (mesure du 2026-10-01 : 6 des 8 organisations egyptiennes et
            # sud-africaines restaient sans secteur, donc plafonnees a medium).
            trouve = _par_nom(
                _noms_de_l_alerte(db, alerte.id),
                noms_par_gang.get(normalise_gang(principal) or principal, {}),
            )
        if trouve is None:
            continue

        alerte.victim_attack_date = _date_d_incident(
            domaine, trouve, intel_par_gang, gangs_alerte
        )
        # Ce que DECLARE le tiers : valeur CALCULEE. La valeur effective
        # (lue partout) est posee par `apply_effective_facts` : la declaration
        # de l'organisation et la correction de l'analyste priment.
        alerte.computed_sector = trouve.activity
        alerte.computed_country = trouve.country
        alerte.compromised_employees = trouve.compromised_employees
        alerte.compromised_users = trouve.compromised_users
        alerte.compromised_thirdparties = trouve.compromised_thirdparties
        alerte.stealer_families = list(trouve.stealer_families) or None
        alerte.last_employee_compromised = _aware(trouve.last_employee_compromised)
        alerte.last_user_compromised = _aware(trouve.last_user_compromised)
        # ⚠️ Marque la MESURE, pas le resultat : sans elle, un compteur a 0
        # serait indiscernable de « jamais mesure ».
        alerte.intel_refreshed_at = maintenant

        resultat.alerts_updated += 1
        renseignees.append(alerte.id)
        if alerte.victim_attack_date:
            resultat.with_attack_date += 1
        if trouve.has_credential_exposure:
            resultat.with_credential_exposure += 1

    db.commit()
    # Valeur EFFECTIVE posee aussitot pour les alertes renseignees : un
    # appelant qui lit `victim_sector` juste apres cette passe ne doit pas
    # voir l'ancienne valeur (declaration et correction priment toujours).
    if renseignees:
        apply_effective_facts(db, alert_ids=renseignees)
    return resultat


@dataclass
class PressOutcome:
    alerts_examined: int = 0
    alerts_confirmed: int = 0  # alertes portant une confirmation apres la passe
    newly_confirmed: int = 0
    gangs_unavailable: int = 0
    success: bool = True
    error: str | None = None


def _gangs_de_l_alerte(alerte: Alert) -> list[str]:
    """Gangs qui revendiquent la victime, gang principal en tete.

    ⚠️ Tous, pas seulement le principal : une victime revendiquee par deux
    gangs peut n'avoir de couverture presse que sous le second."""
    gangs: list[str] = []
    for gang in [alerte.corroborated_group, *(alerte.corroborated_groups or [])]:
        if isinstance(gang, str) and gang.strip() and gang not in gangs:
            gangs.append(gang)
    return gangs


def refresh_press_coverage(db: Session, *, alert_ids=None) -> PressOutcome:
    """Renseigne la confirmation par la presse (migration 0030).

    Derive de la charge ransomware.live DEJA rapatriee par la corroboration
    (`payload_rwl`, en cache 24 h) : aucun appel reseau supplementaire en
    regime normal.

    ⚠️ UNE CONFIRMATION ACQUISE N'EST JAMAIS EFFACEE. Un gang indisponible, ou
    une entree `press` absente d'une passe, ne prouve pas que l'article a
    disparu -- meme principe que la corroboration (« ne pas avoir consulte
    n'est pas avoir cherche »). `press_confirmed_at` garde la date de la
    PREMIERE observation.

    `alert_ids` borne la passe (lecon du piege de portee : un test ne doit
    jamais pouvoir reecrire toutes les alertes reelles)."""
    resultat = PressOutcome()
    requete = select(Alert).where(Alert.corroborated_group.isnot(None))
    if alert_ids is not None:
        requete = requete.where(Alert.id.in_(list(alert_ids)))
    alertes = list(db.execute(requete).scalars())
    resultat.alerts_examined = len(alertes)
    if not alertes:
        return resultat

    # Un appel par GANG (en cache), jamais par victime.
    couverture_par_gang: dict[str, dict] = {}
    for gang in sorted({g for a in alertes for g in _gangs_de_l_alerte(a)}):
        try:
            charge = payload_rwl(gang)
        except Exception:
            logger.warning(
                "Couverture presse indisponible pour %s", gang, exc_info=True
            )
            charge = None
        if charge is None:
            resultat.gangs_unavailable += 1
            continue
        couverture_par_gang[gang] = parse_press_coverage(charge)

    if not couverture_par_gang:
        resultat.success = False
        resultat.error = "aucun historique disponible"
        return resultat

    maintenant = datetime.now(timezone.utc)
    for alerte in alertes:
        domaines = _domaines_de_l_alerte(db, alerte.id)
        trouve = None
        for gang in _gangs_de_l_alerte(alerte):
            index = couverture_par_gang.get(gang)
            if not index:
                continue
            trouve = next((index[d] for d in domaines if d in index), None)
            if trouve is not None:
                break
        if trouve is not None:
            if alerte.press_confirmed_at is None:
                alerte.press_confirmed_at = maintenant
                resultat.newly_confirmed += 1
            # Les liens sont rafraichis s'ils changent (article deplace), mais
            # jamais remplaces par du vide.
            alerte.press_source_url = trouve.source_url or alerte.press_source_url
            alerte.press_evidence_url = trouve.evidence_url or alerte.press_evidence_url
        if alerte.press_confirmed_at is not None:
            resultat.alerts_confirmed += 1

    db.commit()
    return resultat


def apply_effective_facts(db: Session, *, alert_ids=None) -> int:
    """Pose le pays et le secteur EFFECTIFS de chaque alerte : correction de
    l'analyste, sinon valeur declaree pour l'organisation surveillee, sinon
    valeur calculee (tiers). Rend le nombre d'alertes modifiees.

    ⚠️ Doit tourner AVANT le recalcul des severites : la gravite NIS2 lit le
    secteur effectif. Une organisation surveillee dont le secteur est declare
    n'a donc plus besoin que ransomware.live la connaisse pour etre notee.
    Idempotent."""
    requete = select(Alert)
    if alert_ids is not None:
        requete = requete.where(Alert.id.in_(list(alert_ids)))
    alertes = list(db.execute(requete).scalars())
    entites = {
        e.id: e
        for e in db.execute(
            select(Entity).where(
                Entity.id.in_({a.entity_id for a in alertes if a.entity_id})
            )
        ).scalars()
    }
    modifiees = 0
    for alerte in alertes:
        entite = entites.get(alerte.entity_id) if alerte.entity_id else None
        pays = effective_value(
            alerte.country_override,
            entite.country if entite else None,
            alerte.computed_country,
        )
        secteur = effective_value(
            alerte.sector_override,
            entite.sector if entite else None,
            alerte.computed_sector,
        )
        if (pays, secteur) != (alerte.victim_country, alerte.victim_sector):
            alerte.victim_country = pays
            alerte.victim_sector = secteur
            modifiees += 1
    db.commit()
    return modifiees
