"""Echantillon de reference : tirage, annotation, evaluation.

Voir `pipeline/evaluation/gold.py` pour la methode (strates, redressement,
mesures). Ce service ne fait que relier cette logique pure a la base.

⚠️ ANNOTATION A L'AVEUGLE. Rien de ce que ce service renvoie pendant
l'annotation ne contient un verdict de classifieur -- ni regles, ni LLM, ni
modele. L'evaluation, elle, est refusee tant que la passe principale n'est pas
terminee : voir les resultats a mi-parcours orienterait la suite.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.gold_annotation import GoldAnnotation
from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.pipeline.detect.announcement_filter import (
    classify_announcement,
    source_publishes_victims,
)
from app.pipeline.evaluation.gold import (
    VERDICTS,
    Candidate,
    Judged,
    Report,
    cohen_kappa,
    draw_sample,
    evaluate,
)

logger = logging.getLogger(__name__)

# Longueur d'extrait montree a l'annotateur. Assez pour juger une annonce de
# forum ou la page d'une victime ; le plus long document du corpus fait
# 735 797 caracteres, qu'il serait vain d'afficher en entier.
EXTRAIT_MAX = 4000


class GoldError(Exception):
    """Refus explicite, affiche tel quel a l'utilisateur."""


def _kind(collector: str | None) -> str:
    return "victim_site" if source_publishes_victims(collector) else "forum"


# --------------------------------------------------------------------------
# Tirage
# --------------------------------------------------------------------------


def build_sample(db: Session) -> dict:
    """Tire l'echantillon, une seule fois.

    ⚠️ REFUSE si un echantillon existe deja. Retirer effacerait les
    annotations deja faites -- des heures de travail humain -- et changerait
    l'etalon en cours de route. Pour recommencer, il faut vider la table
    deliberement, hors de l'interface."""
    if db.query(GoldAnnotation.id).first() is not None:
        raise GoldError("Un echantillon existe deja : il n'est jamais retire.")

    rows = (
        db.query(RawDocument.id, RawDocument.collector, RawDocument.announcement_class)
        .filter(RawDocument.announcement_class.in_(VERDICTS))
        .filter(RawDocument.title.isnot(None))
        .filter(RawDocument.is_duplicate.is_(False))
        .all()
    )
    candidats = [
        Candidate(str(r.id), _kind(r.collector), r.announcement_class) for r in rows
    ]
    items = draw_sample(candidats)
    for item in items:
        db.add(
            GoldAnnotation(
                document_id=uuid.UUID(item.document_id),
                rank=item.rank,
                control_rank=item.control_rank,
                stratum=item.stratum,
                stratum_population=item.stratum_population,
                sampled_verdict=item.sampled_verdict,
            )
        )
    db.commit()
    logger.info("Echantillon de reference tire : %d documents", len(items))
    return progress(db)


# --------------------------------------------------------------------------
# Annotation
# --------------------------------------------------------------------------


def progress(db: Session) -> dict:
    lignes = db.query(GoldAnnotation).all()
    controle = [g for g in lignes if g.control_rank is not None]
    faits = sum(1 for g in lignes if g.label)
    faits_controle = sum(1 for g in controle if g.control_label)
    if not lignes:
        phase = "empty"
    elif faits < len(lignes):
        phase = "main"
    elif faits_controle < len(controle):
        phase = "control"
    else:
        phase = "done"
    return {
        "phase": phase,
        "total": len(lignes),
        "annotated": faits,
        "control_total": len(controle),
        "control_annotated": faits_controle,
    }


def _serialize(db: Session, g: GoldAnnotation, phase: str) -> dict:
    doc, source = (
        db.query(RawDocument, Source)
        .join(Source, Source.id == RawDocument.source_id)
        .filter(RawDocument.id == g.document_id)
        .one()
    )
    contenu = doc.content or ""
    return {
        "id": str(g.id),
        "phase": phase,
        "position": g.rank if phase == "main" else g.control_rank,
        "title": doc.title,
        "source_name": source.name,
        "source_kind": _kind(doc.collector),
        "published_at": doc.published_at.isoformat() if doc.published_at else None,
        "fetched_at": doc.fetched_at.isoformat() if doc.fetched_at else None,
        # Affichee, jamais cliquable : c'est presque toujours un `.onion`.
        "url": doc.url,
        "content": contenu[:EXTRAIT_MAX],
        "content_length": len(contenu),
        "content_truncated": bool(doc.content_truncated),
        # ⚠️ En passe de CONTROLE, le premier jugement n'est PAS renvoye :
        # le voir ferait mesurer la memoire de l'annotateur, pas sa coherence.
        "label": g.label if phase == "main" else g.control_label,
        "note": g.note if phase == "main" else None,
    }


def get_item(db: Session, phase: str, position: int | None = None) -> dict | None:
    """Le prochain document a juger, ou celui d'une position donnee (pour
    revenir corriger un jugement)."""
    if phase not in ("main", "control"):
        raise GoldError("Phase inconnue.")
    q = db.query(GoldAnnotation)
    if phase == "main":
        if position is not None:
            g = q.filter(GoldAnnotation.rank == position).one_or_none()
        else:
            g = (
                q.filter(GoldAnnotation.label.is_(None))
                .order_by(GoldAnnotation.rank)
                .first()
            )
    else:
        if progress(db)["phase"] == "main":
            raise GoldError(
                "La passe de controle s'ouvre une fois la premiere terminee."
            )
        q = q.filter(GoldAnnotation.control_rank.isnot(None))
        if position is not None:
            g = q.filter(GoldAnnotation.control_rank == position).one_or_none()
        else:
            g = (
                q.filter(GoldAnnotation.control_label.is_(None))
                .order_by(GoldAnnotation.control_rank)
                .first()
            )
    return _serialize(db, g, phase) if g else None


def translate_item(
    db: Session, annotation_id: uuid.UUID, target_lang: str = "fr"
) -> dict:
    """Traduit ce que l'annotateur a SOUS LES YEUX : le titre et l'extrait
    affiche, pas le document entier.

    ⚠️ Demande a l'usage le 2026-09-21 sur un article XSSF en russe. Le
    service de traduction n'a aucune borne de longueur : sur un document de
    15 000 caracteres il tournerait plusieurs minutes. On borne donc a
    `EXTRAIT_MAX`, exactement ce que la page montre -- traduire ce qu'on ne
    lit pas couterait du temps pour rien.

    ⚠️ Modeles installes : russe -> anglais et anglais -> francais (le russe
    passe par l'anglais). Une autre langue leve `GoldError`, avec la langue
    detectee dans le message : mieux vaut « pas de modele pour le portugais »
    qu'une traduction absente sans explication."""
    from langdetect import LangDetectException, detect

    from app.pipeline.enrich.translate import (
        TranslationUnavailableError,
        translate_text,
    )

    g = db.get(GoldAnnotation, annotation_id)
    if g is None:
        raise GoldError("Document absent de l'echantillon.")
    doc = db.get(RawDocument, g.document_id)
    # Garde manquante trouvee par mypy : le document a pu etre supprime
    # depuis le tirage (ex. nettoyage des blobs PAYLOAD) -- erreur 500 sinon.
    if doc is None:
        raise GoldError("Document introuvable : il a ete supprime du corpus.")
    extrait = (doc.content or "")[:EXTRAIT_MAX]
    try:
        source = detect(f"{doc.title or ''}\n{extrait}")
    except LangDetectException as exc:
        raise GoldError("Langue indetectable : contenu trop court.") from exc
    if source == target_lang:
        raise GoldError("Le document est deja dans cette langue.")
    try:
        return {
            "source_lang": source,
            "title": (
                translate_text(doc.title, source, target_lang) if doc.title else None
            ),
            "content": translate_text(extrait, source, target_lang),
        }
    except TranslationUnavailableError as exc:
        raise GoldError(
            f"Aucun modele de traduction pour la langue « {source} »."
        ) from exc


def record(
    db: Session,
    annotation_id: uuid.UUID,
    *,
    phase: str,
    label: str,
    note: str | None,
    username: str,
) -> dict:
    if label not in VERDICTS:
        raise GoldError("Etiquette attendue : leak, noise ou uncertain.")
    g = db.get(GoldAnnotation, annotation_id)
    if g is None:
        raise GoldError("Document absent de l'echantillon.")
    maintenant = datetime.now(timezone.utc)
    if phase == "main":
        g.label = label
        g.note = (note or "").strip() or None
        g.annotated_by = username
        g.annotated_at = maintenant
    elif phase == "control":
        if g.control_rank is None:
            raise GoldError(
                "Ce document n'appartient pas au sous-ensemble de controle."
            )
        g.control_label = label
        g.control_annotated_at = maintenant
    else:
        raise GoldError("Phase inconnue.")
    db.commit()
    return progress(db)


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def disagreements(db: Session) -> list[dict]:
    """Documents ou les regles REJOUEES contredisent l'humain, avec le motif.

    C'est la liste de travail de l'affinage : chaque ligne est soit une regle
    a corriger, soit un cas limite a documenter. Les victimes ecartees a tort
    (`leak` juge, `noise` predit) viennent en tete : c'est l'erreur la plus
    couteuse."""
    lignes = (
        db.query(GoldAnnotation, RawDocument, Source)
        .join(RawDocument, RawDocument.id == GoldAnnotation.document_id)
        .join(Source, Source.id == RawDocument.source_id)
        .filter(GoldAnnotation.label.isnot(None))
        .order_by(GoldAnnotation.rank)
        .all()
    )
    resultat = []
    for g, doc, source in lignes:
        r = classify_announcement(
            doc.title,
            doc.content,
            source_publishes_victims=source_publishes_victims(doc.collector),
        )
        if r.verdict.value != g.label:
            resultat.append(
                {
                    "rank": g.rank,
                    "title": doc.title,
                    "source": source.name,
                    "human": g.label,
                    "rules": r.verdict.value,
                    "reason": r.reason,
                    "note": g.note,
                    "costly": g.label == "leak" and r.verdict.value == "noise",
                }
            )
    resultat.sort(key=lambda d: (not d["costly"], d["rank"]))
    return resultat


def _report_dict(report: Report) -> dict:
    return asdict(report)


def _verdicts(doc: RawDocument) -> tuple[str, str]:
    """(regles REJOUEES, cascade regles + LLM) pour un document.

    Partage par l'evaluation et l'export du jeu de donnees : deux calculs du
    meme verdict finiraient par diverger, et l'experience SetFit serait alors
    comparee a autre chose que ce que l'evaluation de reference rapporte."""
    regles = classify_announcement(
        doc.title,
        doc.content,
        source_publishes_victims=source_publishes_victims(doc.collector),
    ).verdict.value
    cascade = regles
    if regles == "uncertain" and doc.llm_class in VERDICTS:
        cascade = doc.llm_class
    return regles, cascade


def evaluate_gold(db: Session, *, allow_partial: bool = False) -> dict:
    """Confronte les regles (REJOUEES) et la cascade regles + LLM a
    l'annotation humaine.

    ⚠️ Les regles sont rejouees sur le document, pas relues en base : c'est ce
    qui permet de mesurer une correction de regle contre la meme reference.
    Le verdict LLM, lui, est celui stocke -- il n'existe que pour les
    documents `uncertain` deja arbitres, et la couverture est rendue."""
    etat = progress(db)
    if etat["phase"] in ("empty", "main") and not allow_partial:
        raise GoldError(
            "Evaluation disponible une fois la passe principale terminee : "
            "voir les resultats a mi-parcours orienterait la suite."
        )

    lignes = (
        db.query(GoldAnnotation, RawDocument)
        .join(RawDocument, RawDocument.id == GoldAnnotation.document_id)
        .filter(GoldAnnotation.label.isnot(None))
        .all()
    )
    # Poids de redressement : population de la strate / items TIRES dans la
    # strate (et non annotes -- sinon une annotation partielle fausserait les
    # poids).
    tires: dict[str, int] = {}
    for (strate,) in db.query(GoldAnnotation.stratum).all():
        tires[strate] = tires.get(strate, 0) + 1

    series: dict[str, list[Judged]] = {"rules": [], "rules_llm": []}
    llm_couverts = 0
    for g, doc in lignes:
        if g.label is None:  # exclu par le filtre SQL ci-dessus
            continue
        kind = _kind(doc.collector)
        poids = g.stratum_population / tires[g.stratum]
        regles, cascade = _verdicts(doc)
        series["rules"].append(Judged(g.label, regles, kind, poids))
        if regles == "uncertain" and doc.llm_class in VERDICTS:
            llm_couverts += 1
        series["rules_llm"].append(Judged(g.label, cascade, kind, poids))

    resultat: dict = {"progress": etat, "classifiers": {}}
    for nom, items in series.items():
        resultat["classifiers"][nom] = {
            "all": _report_dict(evaluate(items)),
            "victim_site": _report_dict(
                evaluate([i for i in items if i.kind == "victim_site"])
            ),
            "forum": _report_dict(evaluate([i for i in items if i.kind == "forum"])),
        }
    resultat["llm_coverage"] = {
        "uncertain_by_rules": sum(
            1 for i in series["rules"] if i.predicted == "uncertain"
        ),
        "arbitrated_by_llm": llm_couverts,
    }

    paires = [
        (g.label, g.control_label)
        for g, _ in lignes
        if g.label is not None and g.control_label is not None
    ]
    resultat["annotator_consistency"] = {
        "pairs": len(paires),
        "raw_agreement": (
            (sum(1 for a, b in paires if a == b) / len(paires)) if paires else None
        ),
        "kappa": cohen_kappa(paires),
    }
    return resultat
