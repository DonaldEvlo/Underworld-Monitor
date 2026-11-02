"""Orchestration de la corroboration RansomLook : recupere le flux et les
historiques de gangs, confronte les VICTIMES en base, et agrege le resultat au
niveau des alertes.

Separation des roles (voir CONTRIBUTING.md §3.3) :
  - `pipeline/enrich/ransomlook_corroboration.py` = logique pure (index,
    decision par victime, perimetre), testable sans reseau ni base ;
  - ce service = acces base + appels reseau + cache ;
  - `worker/tasks/` = wrapper mince.

**Unite de confrontation : la victime** (2026-09-11). Un document de site de
fuite = une victime ; ses detections `domain` et `organization` recoivent le
MEME verdict. Auparavant chaque domaine etait confronte seul au flux des 30
derniers jours : « exclusive » y voulait surtout dire « hors fenetre ».

**Historique complet des gangs, en cache 24 h.** Un appel clearnet par gang
dont nous lisons le site (une quinzaine), une fois par jour -- pas a chaque
passe horaire. Le flux recent reste interroge a chaque passe (un appel).

**Un echec reseau ne degrade jamais l'existant.** Flux injoignable : rien
n'est ecrit. Historique d'un gang injoignable : ses victimes introuvables dans
le flux gardent leur statut precedent -- les marquer « vues par nous seuls »
sans avoir consulte l'historique reproduirait exactement le defaut corrige.
"""

from __future__ import annotations

from typing import cast

import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import get_redis
from app.db.models.alert import Alert, AlertDetection
from app.db.models.detection import Detection
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.pipeline.collect.ransomlook.scraper import fetch_ransomlook_posts
from app.pipeline.enrich.ransomlook_corroboration import (
    CORROBORABLE_TYPES,
    OBSERVER_RANSOMWARE_LIVE,
    CorroborationStatus,
    VictimCorroboration,
    build_victim_index,
    corroborate_victim,
    domain_candidates,
    gang_slug_for_source,
    group_evidence_api_url,
    is_corroborable,
    normalise_gang,
    parse_group_history,
)
from app.pipeline.enrich.ransomware_live import (
    group_profile_url as rwl_group_profile_url,
)
from app.pipeline.enrich.ransomware_live import (
    group_victims_url as rwl_group_victims_url,
)
from app.pipeline.enrich.ransomware_live import (
    profile_payload as rwl_profile_payload,
)
from app.pipeline.enrich.ransomware_live import (
    parse_group_victims as rwl_parse_group_victims,
)

logger = logging.getLogger(__name__)

RANSOMLOOK_BASE_URL = "https://www.ransomlook.io"

# L'historique LockBit fait plus de 4000 annonces : de la marge.
_TIMEOUT_HISTORIQUE = 120
_HISTORIQUE_TTL_SECONDS = 24 * 3600
_HISTORIQUE_KEY = "ransomlook_history:{gang}"
_RWL_HISTORIQUE_KEY = "ransomwarelive_history:{gang}"
# ⚠️ Charge BRUTE des victimes d'un gang chez ransomware.live, mise en cache a
# part. Une SEULE requete alimente ainsi la corroboration (qui n'a besoin que
# du titre et de la date) ET les renseignements par victime (qui ont besoin de
# `attackdate`, `activity`, `infostealer`) -- voir victim_intel_service.
#
# ⚠️ RATE LIMIT MESURE LE 2026-09-15 : ~1 requete par MINUTE sur cette API
# (elle repond `{"message": "1 per 1 minute"}`, avec un HTTP 200 -- donc un
# `raise_for_status()` ne le verrait pas). Derive deux usages d'un seul appel
# plutot que de doubler les requetes : a 17 gangs, doubler couterait 17
# minutes d'attente de plus par passe.
_RWL_PAYLOAD_KEY = "ransomwarelive_payload:{gang}"
# Gangs revendicateurs HORS de nos sources dont on va chercher l'historique
# pour obtenir la capture par victime. Borne : quelques-uns, jamais les 80.
_MAX_GANGS_SUPPLEMENTAIRES = 10

# Plafond de detections confrontees en une passe. Meme esprit que
# `_MAX_DETECTIONS_LOADED` dans alert_service.
_MAX_DETECTIONS = 20_000

_CORROBORATED = CorroborationStatus.CORROBORATED.value
_EXCLUSIVE = CorroborationStatus.EXCLUSIVE.value
_NOT_APPLICABLE = CorroborationStatus.NOT_APPLICABLE.value


@dataclass(frozen=True)
class CorroborationOutcome:
    """Compte rendu d'une passe, pour le worker et l'API."""

    success: bool
    feed_size: int = 0
    detections_checked: int = 0
    detections_corroborated: int = 0
    detections_not_applicable: int = 0
    victims_checked: int = 0
    victims_corroborated: int = 0
    histories_loaded: int = 0
    histories_unavailable: tuple[str, ...] = ()
    alerts_updated: int = 0
    alerts_corroborated: int = 0
    error: str | None = None


def _cached_history(
    gang: str,
    cache_key: str,
    url: str,
    parse,
    observateur: str,
    *,
    ttl_seconds: int | None = None,
    timeout: int | None = None,
) -> list[dict] | None:
    """Historique complet d'un gang chez UN observateur, cache 24 h.

    `None` = INDISPONIBLE (rien n'est mesure -- reseau/cache en echec) ;
    `[]` = l'observateur ne suit pas ce gang (mesure VALIDE, HTTP 404).
    La distinction est decisive : « vue par nous seuls » n'est permis que si
    l'observateur a repondu (voir garde dans corroborate_corpus)."""
    cle = cache_key.format(gang=normalise_gang(gang) or gang)
    redis = None
    try:
        redis = get_redis()
        cache = cast("str | None", redis.get(cle))
        if cache is not None:
            return json.loads(cache)
    except Exception:
        logger.warning(
            "Cache des historiques %s indisponible", observateur, exc_info=True
        )

    try:
        reponse = requests.get(
            url,
            timeout=timeout or _TIMEOUT_HISTORIQUE,
            headers={"User-Agent": "threat-intel-platform"},
        )
        if reponse.status_code == 404:
            annonces: list[dict] = []
        else:
            reponse.raise_for_status()
            annonces = parse(reponse.json())
    except Exception:
        logger.warning(
            "Historique %s indisponible pour %s", observateur, gang, exc_info=True
        )
        return None

    # ⚠️ Ne JAMAIS mettre en cache une indisponibilite. `annonces is None`
    # signifie « rien n'a ete mesure » : la cacher 24 h transformerait un
    # hoquet de rate limit (l'API repond `{"message": "1 per 1 minute"}` en
    # HTTP 200) en absence de mesure d'une journee entiere, pour tout un gang.
    if redis is not None and annonces is not None:
        try:
            redis.set(
                cle,
                json.dumps(annonces),
                ex=ttl_seconds or _HISTORIQUE_TTL_SECONDS,
            )
        except Exception:
            logger.warning(
                "Historique %s/%s non mis en cache", observateur, gang, exc_info=True
            )
    return annonces


def _historique(gang: str) -> list[dict] | None:
    """Historique RansomLook d'un gang (`/api/group/<gang>`)."""
    return _cached_history(
        gang,
        _HISTORIQUE_KEY,
        group_evidence_api_url(gang),
        parse_group_history,
        "RansomLook",
    )


def payload_rwl(gang: str) -> list | None:
    """Charge BRUTE des victimes d'un gang chez ransomware.live, cache 24 h.

    Point d'entree UNIQUE vers cette API : la corroboration et les
    renseignements par victime en derivent tous deux, pour ne payer qu'une
    requete (rate limit ~1/min, voir `_RWL_PAYLOAD_KEY`).

    Memes conventions que `_cached_history` : `None` = indisponible (rien
    n'est mesure), `[]` = gang non suivi (mesure valide)."""
    return _cached_history(
        gang,
        _RWL_PAYLOAD_KEY,
        rwl_group_victims_url(gang),
        # La « transformation » est l'identite : on garde le payload tel quel.
        # ⚠️ Un payload non-liste (message de rate limit servi en HTTP 200)
        # est ramene a None -- sinon il serait mis en cache 24 h comme si le
        # gang n'avait aucune victime, et « vue par nous seuls » deviendrait
        # faux pour toutes ses victimes.
        lambda charge: charge if isinstance(charge, list) else None,
        "ransomware.live",
    )


_RWL_PROFIL_KEY = "ransomwarelive_profile:{gang}"
# Un mode operatoire change rarement : 7 jours de cache, pour rester loin du
# rate limit (~1/min) alors que l'appel part a l'ouverture d'un dossier.
_RWL_PROFIL_TTL_SECONDS = 7 * 24 * 3600
# Appel INTERACTIF (ouverture du dossier) : on n'attend pas 120 s comme pour un
# historique de plusieurs milliers d'annonces.
_TIMEOUT_PROFIL = 20


def payload_rwl_profile(gang: str) -> list | None:
    """Profil (mode operatoire) d'un gang chez ransomware.live, cache 7 jours.

    Point d'entree UNIQUE vers `/v2/group/<gang>`. Memes conventions que
    `_cached_history` : `None` = indisponible (reseau, ou limite de debit
    servie en HTTP 200 -- jamais mise en cache), `[]` = gang non suivi
    (HTTP 404), `[profil]` sinon."""
    return _cached_history(
        gang,
        _RWL_PROFIL_KEY,
        rwl_group_profile_url(gang),
        rwl_profile_payload,
        "ransomware.live (profil)",
        ttl_seconds=_RWL_PROFIL_TTL_SECONDS,
        timeout=_TIMEOUT_PROFIL,
    )


def rwl_payload_cached(gang: str) -> bool:
    """La charge ransomware.live de ce gang est-elle deja en cache ? Permet a
    un appelant de ne compter que les VRAIS appels reseau dans son budget
    (rate limit ~1/min). En cas de doute (Redis indisponible) : non."""
    try:
        cle = _RWL_PAYLOAD_KEY.format(gang=normalise_gang(gang) or gang)
        return bool(get_redis().exists(cle))
    except Exception:
        return False


def _historique_rwl(gang: str) -> list[dict] | None:
    """Victimes ransomware.live d'un gang, sous la forme attendue par
    `build_victim_index`. Derive de la charge brute mise en cache."""
    charge = payload_rwl(gang)
    if charge is None:
        return None
    return rwl_parse_group_victims(charge)


def _termes_de_victime(
    document: RawDocument, detections: list[Detection]
) -> tuple[list[str], list[str]]:
    """Domaines et raisons sociales qui designent la victime d'un document."""
    domaines: list[str] = []
    noms: list[str] = []
    for valeur in [document.title or ""] + [d.value_masked or "" for d in detections]:
        if not valeur:
            continue
        # Le type ne suffit pas : 873 detections `organization` portent en
        # realite un domaine (mesure du 2026-09-04).
        (domaines if domain_candidates(valeur) else noms).append(valeur)
    return domaines, noms


def _appliquer(
    detection: Detection, verdict: VictimCorroboration, now: datetime
) -> None:
    principale = verdict.primary
    detection.corroboration_status = verdict.status.value
    detection.corroborated_at = now
    detection.corroboration_match = verdict.match
    detection.corroborated_groups = verdict.groups or None
    detection.corroborated_group = principale.group_name if principale else None
    detection.corroboration_first_seen_at = verdict.first_seen_at
    # Observateurs tiers ayant vu la victime (RansomLook, ransomware.live) --
    # jamais un gang. « exclusive » -> aucun.
    detection.corroboration_observers = verdict.observers or None
    # Preuve consultable : sans lien, une corroboration reste une affirmation.
    detection.corroboration_evidence_url = (
        principale.evidence_url if principale else None
    )


def _sans_objet(detection: Detection, now: datetime) -> None:
    detection.corroboration_status = _NOT_APPLICABLE
    detection.corroborated_at = now
    detection.corroboration_match = None
    detection.corroborated_groups = None
    detection.corroborated_group = None
    detection.corroboration_first_seen_at = None
    detection.corroboration_observers = None
    detection.corroboration_evidence_url = None


def corroborate_corpus(db: Session, *, alert_id=None) -> CorroborationOutcome:
    """Confronte les victimes au flux et aux historiques RansomLook, puis met a
    jour les alertes concernees.

    `alert_id` restreint la passe aux documents d'une seule alerte (chemin
    interactif) ; sans lui, tout le corpus corroborable est revisite."""
    try:
        posts = fetch_ransomlook_posts(RANSOMLOOK_BASE_URL)
    except Exception as exc:  # noqa: BLE001 -- on veut degrader proprement
        # Volontairement non fatal : la corroboration est un enrichissement,
        # pas le livrable. Une panne de RansomLook ne doit ni faire echouer
        # l'alerting ni reecrire des statuts en base.
        logger.warning("Corroboration RansomLook indisponible: %s", exc)
        return CorroborationOutcome(success=False, error=str(exc))

    now = datetime.now(timezone.utc)

    # --- 1. Detections candidates, avec leur document et leur source --------
    requete = (
        db.query(Detection, RawDocument, Source)
        .join(RawDocument, RawDocument.id == Detection.document_id)
        .join(Source, Source.id == RawDocument.source_id)
        .filter(Detection.type.in_(tuple(CORROBORABLE_TYPES)))
    )
    if alert_id is not None:
        documents_alerte = (
            select(Detection.document_id)
            .join(AlertDetection, AlertDetection.detection_id == Detection.id)
            .where(AlertDetection.alert_id == alert_id)
        )
        requete = requete.filter(Detection.document_id.in_(documents_alerte))
    lignes = requete.limit(_MAX_DETECTIONS).all()

    victimes: dict = {}
    sans_objet: list[Detection] = []
    for detection, document, source in lignes:
        if not is_corroborable(
            detection.type, detection.value_masked, document.collector
        ):
            sans_objet.append(detection)
            continue
        victime = victimes.setdefault(
            document.id,
            {
                "document": document,
                "gang": gang_slug_for_source(source.name),
                "detections": [],
            },
        )
        victime["detections"].append(detection)

    # --- 2. Historiques des gangs, chez DEUX observateurs --------------------
    # RansomLook ET ransomware.live. Ce dernier couvre des gangs que RansomLook
    # ignore (APT73/CMD/PEAR : 0 % -> 94 % mesure le 2026-09-14). Les deux
    # lisent le meme DLS -- non independants, mais leur UNION etend la
    # couverture.
    gangs = sorted({v["gang"] for v in victimes.values() if v["gang"]})
    historiques = {g: h for g in gangs if (h := _historique(g)) is not None}
    rwl = {g: h for g in gangs if (h := _historique_rwl(g)) is not None}
    # ⚠️ « Vue par nous seuls » n'est permis que si TOUS les observateurs ont
    # repondu pour ce gang : si ransomware.live (qui couvre APT73) est
    # injoignable, ne PAS retomber en « exclusive » -- c'est une absence de
    # mesure, pas une absence de victime.
    pleinement_consultes = set(historiques) & set(rwl)
    indisponibles = tuple(g for g in gangs if g not in pleinement_consultes)

    def decider() -> dict:
        index = build_victim_index(posts, historiques, {OBSERVER_RANSOMWARE_LIVE: rwl})
        return {
            doc_id: corroborate_victim(
                *_termes_de_victime(v["document"], v["detections"]),
                index,
                expected_group=v["gang"],
            )
            for doc_id, v in victimes.items()
        }

    verdicts = decider()

    # Gangs revendicateurs sans historique charge (vus dans le flux, hors de
    # nos sources) : on va chercher leur historique pour la capture par
    # victime, puis on redecide -- en memoire, sans autre appel.
    supplementaires = sorted(
        {
            v.primary.group_name
            for v in verdicts.values()
            if v.primary is not None
            and v.primary.screenshot_path is None
            and normalise_gang(v.primary.group_name)
            not in {normalise_gang(g) for g in historiques}
        }
    )[:_MAX_GANGS_SUPPLEMENTAIRES]
    for gang in supplementaires:
        historique = _historique(gang)
        if historique is not None:
            historiques[gang] = historique
    if supplementaires:
        verdicts = decider()

    # --- 3. Application -------------------------------------------------------
    checked = corroborated = victims_checked = victims_corroborated = 0
    for doc_id, victime in victimes.items():
        verdict = verdicts[doc_id]
        gang = victime["gang"]
        # ⚠️ « Vue par nous seuls » exige d'avoir consulte l'historique du
        # gang. Sans lui, l'absence dans le flux des 30 derniers jours ne dit
        # rien : on ne touche pas au statut existant.
        if verdict.status is CorroborationStatus.EXCLUSIVE and (
            not gang or gang not in pleinement_consultes
        ):
            continue
        victims_checked += 1
        if verdict.status is CorroborationStatus.CORROBORATED:
            victims_corroborated += 1
        for detection in victime["detections"]:
            _appliquer(detection, verdict, now)
            checked += 1
            if verdict.status is CorroborationStatus.CORROBORATED:
                corroborated += 1

    for detection in sans_objet:
        _sans_objet(detection, now)

    # --- 4. Niveau ALERTE -----------------------------------------------------
    alerts_query = db.query(Alert)
    if alert_id is not None:
        alerts_query = alerts_query.filter(Alert.id == alert_id)
    alerts = alerts_query.all()

    alerts_updated = alerts_corroborated = 0
    for alert in alerts:
        rows = (
            db.query(Detection)
            .join(AlertDetection, AlertDetection.detection_id == Detection.id)
            .filter(AlertDetection.alert_id == alert.id)
            .filter(Detection.type.in_(tuple(CORROBORABLE_TYPES)))
            .all()
        )
        confirmees = [r for r in rows if r.corroboration_status == _CORROBORATED]
        alert.corroborated_count = len(confirmees)
        alert.corroborated_at = now
        if confirmees:
            alert.corroboration_status = _CORROBORATED
            principaux = [
                c.corroborated_group for c in confirmees if c.corroborated_group
            ]
            alert.corroborated_group = (
                Counter(principaux).most_common(1)[0][0] if principaux else None
            )
            tous: list[str] = []
            for c in confirmees:
                for g in c.corroborated_groups or (
                    [c.corroborated_group] if c.corroborated_group else []
                ):
                    if g not in tous:
                        tous.append(g)
            alert.corroborated_groups = tous or None
            observateurs: set[str] = set()
            for c in confirmees:
                observateurs |= set(c.corroboration_observers or [])
            alert.corroboration_observers = sorted(observateurs) or None
            dates = [
                c.corroboration_first_seen_at
                for c in confirmees
                if c.corroboration_first_seen_at
            ]
            alert.corroboration_first_seen_at = min(dates) if dates else None
            alert.corroboration_evidence_url = next(
                (
                    c.corroboration_evidence_url
                    for c in confirmees
                    if c.corroborated_group == alert.corroborated_group
                    and c.corroboration_evidence_url
                ),
                None,
            )
            alerts_corroborated += 1
        else:
            if any(r.corroboration_status == _EXCLUSIVE for r in rows):
                # « Nous seuls voyons cette victime », historique du gang
                # consulte. Ce n'est PAS un defaut de fiabilite.
                statut = _EXCLUSIVE
            elif rows and all(r.corroboration_status == _NOT_APPLICABLE for r in rows):
                # Mentions de forum ou infrastructure : pas une revendication.
                statut = _NOT_APPLICABLE
            else:
                statut = CorroborationStatus.UNKNOWN.value
            alert.corroboration_status = statut
            alert.corroborated_group = None
            alert.corroborated_groups = None
            alert.corroboration_observers = None
            alert.corroboration_first_seen_at = None
            alert.corroboration_evidence_url = None
        alerts_updated += 1

    db.commit()

    logger.info(
        "Corroboration: %d gang(s) chez RansomLook, %d chez ransomware.live, "
        "%d pleinement consultes",
        len(historiques),
        len(rwl),
        len(pleinement_consultes),
    )
    if indisponibles:
        logger.warning(
            "Corroboration: gang(s) non pleinement consultes %s -- statuts conserves",
            ", ".join(indisponibles),
        )
    return CorroborationOutcome(
        success=True,
        feed_size=len(posts),
        detections_checked=checked,
        detections_corroborated=corroborated,
        detections_not_applicable=len(sans_objet),
        victims_checked=victims_checked,
        victims_corroborated=victims_corroborated,
        histories_loaded=len(historiques),
        histories_unavailable=indisponibles,
        alerts_updated=alerts_updated,
        alerts_corroborated=alerts_corroborated,
    )
