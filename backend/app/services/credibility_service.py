"""Credibilite des alertes (plan de credibilite, phase 5) : base -> faits ->
`pipeline/alerting/credibility.assess` -> base.

⚠️ LE STATUT DE PUBLICATION SE LIT SUR TOUTE LA VICTIME, pas sur les seuls
documents qui portent la detection. La completion des descriptions cree un
second document par victime (l'apercu tronque, puis la page de detail), et le
libelle « PUBLISHED » peut ne figurer que sur l'un des deux. Mesure du
2026-09-24 : lecture par detection seule -> 7 alertes « inconnues » ; par
victime (meme source, meme URL) -> 1 seule, Organisation Exemple, qui vient d'un forum.

⚠️ NE TOUCHE NI A LA GRAVITE, NI AU STATUT, NI AU RESUME : c'est un axe a
part, et ces champs portent des decisions d'analyste ou une autre echelle.

⚠️ `alert_ids` BORNE LA PORTEE (lecon du piege de portee, rencontre quatre
fois) : sans lui, la passe porte sur toute la table -- le bon defaut pour la
production, jamais pour un test.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.alert import Alert, AlertDetection
from app.db.models.detection import Detection
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.pipeline.alerting.claim_history import classify_claims
from app.pipeline.alerting.credibility import CredibilityInput, assess
from app.pipeline.collect.source_naming import group_display_name
from app.pipeline.collect.publication_status import (
    EVIDENCE_KEY,
    STATUS_KEY,
    best_status,
)
from app.pipeline.detect.announcement_filter import source_publishes_victims
from app.pipeline.enrich.ransomlook_corroboration import (
    domain_candidates,
    gang_slug_for_source,
    name_key,
    normalise_gang,
)

logger = logging.getLogger(__name__)


def _charge_en_cache(gang: str) -> list | None:
    """Victimes ransomware.live du gang, SEULEMENT si deja en cache.

    La passe de credibilite ne declenche aucun appel reseau : dans
    `alerts.generate`, la corroboration qui la precede a deja rapatrie les
    gangs de nos sources. Absente = pas de mesure pour ce gang, jamais « pas
    de revendication »."""
    from app.services.corroboration_service import payload_rwl, rwl_payload_cached

    try:
        if not rwl_payload_cached(gang):
            return None
        return payload_rwl(gang)
    except Exception:
        logger.warning("Historique indisponible pour %s", gang, exc_info=True)
        return None


def _date(texte) -> datetime | None:
    if not texte:
        return None
    try:
        date = datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    except ValueError:
        return None
    # Sans fuseau = UTC (meme convention que la corroboration).
    return date if date.tzinfo else date.replace(tzinfo=timezone.utc)


def _index_publications(charge: list) -> dict[str, datetime]:
    """Cle de victime (domaine candidat, ou « nom: » + raison sociale
    normalisee) -> PREMIERE date de publication chez ce gang (`discovered`,
    jamais `attackdate`, parfois une date d'import en lot)."""
    index: dict[str, datetime] = {}
    for victime in charge:
        date = _date(victime.get("discovered"))
        if date is None:
            continue
        cles = set(domain_candidates(victime.get("domain"))) | set(
            domain_candidates(victime.get("victim"))
        )
        cle_nom = name_key(victime.get("victim"))
        if cle_nom:
            cles.add("nom:" + cle_nom)
        for cle in cles:
            if cle not in index or date < index[cle]:
                index[cle] = date
    return index


def _date_de(valeurs: set[str], index: dict[str, datetime]) -> datetime | None:
    dates = [index[c] for v in valeurs for c in domain_candidates(v) if c in index]
    for valeur in valeurs:
        cle = name_key(valeur)
        if cle and "nom:" + cle in index:
            dates.append(index["nom:" + cle])
    return min(dates) if dates else None


def _gang_du_document(document: RawDocument, source: Source, groupes: list[str]) -> str:
    """Gang dont le site a publie CE document -- notre revendication.

    Deduit de la source (ou du `group_name` d'un document RansomLook), avec
    repli sur le premier des `corroborated_groups`, que la corroboration
    ordonne gang de la source en tete."""
    if (document.collector or "").lower() == "ransomlook":
        gang = normalise_gang((document.source_meta or {}).get("group_name"))
        if gang in groupes:
            return gang
    gang = normalise_gang(gang_slug_for_source(source.name))
    return gang if gang in groupes else groupes[0]


def _libelle(valeurs: set[str]) -> str:
    """Nom de la victime pour l'analyste : son domaine s'il y en a un."""
    domaines = sorted(v for v in valeurs if domain_candidates(v))
    return (domaines or sorted(valeurs))[0].removeprefix("www.")


def _faits_par_alerte(db: Session, alertes: list[Alert]) -> dict:
    """Faits agreges par alerte, en DEUX requetes quel que soit le nombre
    d'alertes (jamais une requete par alerte)."""
    ids = [a.id for a in alertes]
    # 1. Documents porteurs des detections de chaque alerte.
    porteurs = (
        db.query(
            AlertDetection.alert_id,
            RawDocument,
            Source,
            Detection.corroborated_groups,
            Detection.value_masked,
        )
        .join(Detection, Detection.id == AlertDetection.detection_id)
        .join(RawDocument, RawDocument.id == Detection.document_id)
        .join(Source, Source.id == RawDocument.source_id)
        .filter(AlertDetection.alert_id.in_(ids))
        .all()
    )
    victimes_par_alerte: dict = defaultdict(set)
    sources: dict = {}
    # Revendications multiples (phase 4) : mesurees PAR VICTIME (un document
    # de site de fuite = une victime), jamais par alerte -- une alerte
    # REGIONALE regroupe plusieurs victimes d'un gang chacune (Exemple/krybit
    # + Suivi Flotte/direwolf) : deux gangs dans l'agregat, aucune victime
    # revendiquee deux fois. Les `corroborated_groups` d'une detection portent
    # TOUS les gangs qui publient cette victime.
    multiples: dict = {}
    for alert_id, document, source, groupes, valeur in porteurs:
        victimes_par_alerte[alert_id].add((document.source_id, document.url))
        sources[document.source_id] = source
        gangs = list(dict.fromkeys(normalise_gang(g) for g in groupes or [] if g))
        if len(gangs) < 2:
            continue
        entree = multiples.setdefault(
            (alert_id, document.source_id, document.url),
            {
                "propre": _gang_du_document(document, source, gangs),
                "gangs": set(),
                "valeurs": set(),
            },
        )
        entree["gangs"].update(gangs)
        if valeur and "*" not in valeur:
            entree["valeurs"].add(valeur.strip().lower())

    index_par_gang: dict[str, dict | None] = {}

    def index_de(gang: str) -> dict | None:
        if gang not in index_par_gang:
            charge = _charge_en_cache(gang)
            index_par_gang[gang] = (
                _index_publications(charge) if charge is not None else None
            )
        return index_par_gang[gang]

    republications_par_alerte: dict = defaultdict(set)
    disputes_par_alerte: dict = defaultdict(set)
    for (alert_id, _, _), entree in multiples.items():
        if not entree["valeurs"]:
            continue
        premieres: dict[str, datetime | None] = {}
        for gang in entree["gangs"]:
            index = index_de(gang)
            if index is not None:
                premieres[gang] = _date_de(entree["valeurs"], index)
        historique = classify_claims(entree["propre"], premieres)
        libelle = _libelle(entree["valeurs"])
        if historique.republished_from is not None:
            gang, date = historique.republished_from
            republications_par_alerte[alert_id].add(
                (libelle, gang, date.date().isoformat())
            )
        if historique.disputed_with:
            disputes_par_alerte[alert_id].add((libelle, historique.disputed_with))

    # 2. Tous les documents de ces victimes (meme source, meme URL).
    cles = {cle for ens in victimes_par_alerte.values() for cle in ens}
    documents_par_victime: dict = defaultdict(list)
    if cles:
        for document in (
            db.query(RawDocument)
            .filter(RawDocument.source_id.in_({s for s, _ in cles}))
            .filter(RawDocument.url.in_({u for _, u in cles}))
            .all()
        ):
            cle = (document.source_id, document.url)
            if cle in cles:
                documents_par_victime[cle].append(document)

    faits = {}
    for alerte in alertes:
        victimes = victimes_par_alerte.get(alerte.id, set())
        documents = [d for cle in victimes for d in documents_par_victime.get(cle, [])]
        statuts = [(d.source_meta or {}).get(STATUS_KEY) for d in documents]
        meilleur = best_status(statuts)
        porteur = next(
            (
                d
                for d in documents
                if meilleur and (d.source_meta or {}).get(STATUS_KEY) == meilleur
            ),
            documents[0] if documents else None,
        )
        source = sources.get(porteur.source_id) if porteur is not None else None
        faits[alerte.id] = CredibilityInput(
            has_documents=bool(documents),
            press_confirmed=alerte.press_confirmed_at is not None,
            publication_status=meilleur,
            publication_evidence=(
                (porteur.source_meta or {}).get(EVIDENCE_KEY)
                if porteur is not None and meilleur
                else None
            ),
            publication_source=group_display_name(source.name) if source else None,
            from_victim_site=any(
                source_publishes_victims(d.collector) for d in documents
            ),
            republications=tuple(sorted(republications_par_alerte.get(alerte.id, ()))),
            disputes=tuple(sorted(disputes_par_alerte.get(alerte.id, ()))),
        )
    return faits


def refresh_alert_credibility(db: Session, *, alert_ids=None) -> dict:
    """Evalue la credibilite des alertes et n'ecrit que ce qui change.

    Idempotent : une seconde passe rend `modifiees: 0`."""
    requete = db.query(Alert)
    if alert_ids is not None:
        requete = requete.filter(Alert.id.in_(list(alert_ids)))
    alertes = requete.all()
    if not alertes:
        return {"examinees": 0, "modifiees": 0, "par_niveau": {}}

    faits = _faits_par_alerte(db, alertes)
    maintenant = datetime.now(timezone.utc)
    par_niveau: dict[str, int] = defaultdict(int)
    modifiees = 0
    for alerte in alertes:
        resultat = assess(faits[alerte.id])
        par_niveau[resultat.level.value] += 1
        if (alerte.credibility_level, alerte.credibility_evidence) != (
            resultat.level.value,
            resultat.evidence,
        ):
            alerte.credibility_level = resultat.level.value
            alerte.credibility_evidence = resultat.evidence[:500]
            alerte.credibility_assessed_at = maintenant
            modifiees += 1
    if modifiees:
        db.commit()
    return {
        "examinees": len(alertes),
        "modifiees": modifiees,
        "par_niveau": dict(par_niveau),
    }


def observations_for_validation(db: Session) -> tuple[list, dict]:
    """Victimes de nos sites de fuite appariees a ransomware.live, pour la
    validation de la phase 6 (`app.scripts.evaluate_credibility`).

    Lecture seule. Une victime = (source, URL), statut = meilleur statut de
    ses documents. Appariement par domaine (labels) puis par nom normalise,
    BORNE AU GANG de la source -- meme doctrine que la corroboration : un meme
    nom chez un autre gang peut designer une autre organisation.

    Rend (observations, compteurs de couverture)."""
    from app.pipeline.enrich.ransomlook_corroboration import (
        domain_candidates,
        gang_slug_for_source,
        name_key,
    )
    from app.pipeline.evaluation.credibility_eval import Observation
    from app.services.corroboration_service import payload_rwl

    lignes = (
        db.query(RawDocument, Source)
        .join(Source, Source.id == RawDocument.source_id)
        .filter(RawDocument.collector.ilike("%dls%"))
        .all()
    )
    victimes: dict = defaultdict(
        lambda: {"statuts": [], "termes": set(), "source": None}
    )
    for document, source in lignes:
        v = victimes[(source.id, document.url)]
        v["source"] = source.name
        meta = document.source_meta or {}
        v["statuts"].append(meta.get(STATUS_KEY))
        for terme in (document.title, meta.get("victim_site"), meta.get("victim_name")):
            if terme:
                v["termes"].add(terme)

    # Un appel (en cache 24 h) par GANG, jamais par victime.
    index: dict = {}
    for nom_source in {v["source"] for v in victimes.values()}:
        gang = gang_slug_for_source(nom_source)
        charge = payload_rwl(gang) if gang else None
        domaines: dict[str, bool] = {}
        noms: dict[str, bool] = {}
        for victime in charge or []:
            presse = bool(victime.get("press"))
            for candidat in domain_candidates(victime.get("domain") or ""):
                domaines[candidat] = domaines.get(candidat, False) or presse
            cle = name_key(victime.get("victim"))
            if cle:
                noms[cle] = noms.get(cle, False) or presse
        index[nom_source] = (gang, charge is not None, domaines, noms)

    observations: list[Observation] = []
    indisponibles: list[str | None] = []
    couverture: dict = {
        "victimes": len(victimes),
        "non_appariees": 0,
        "gangs_indisponibles": indisponibles,
    }
    for v in victimes.values():
        gang, disponible, domaines, noms = index[v["source"]]
        if not disponible or gang is None:
            if gang not in indisponibles:
                indisponibles.append(gang)
            continue
        confirmee: bool | None = None
        for terme in v["termes"]:
            for candidat in domain_candidates(terme):
                if candidat in domaines:
                    confirmee = confirmee or domaines[candidat]
            cle = name_key(terme)
            if confirmee is None and cle in noms:
                confirmee = noms[cle]
        if confirmee is None:
            couverture["non_appariees"] += 1
            continue
        observations.append(
            Observation(
                gang=gang,
                status=best_status(v["statuts"]) or "unknown",
                press=confirmee,
            )
        )
    return observations, couverture
