"""Changements d'adresse des sources : repérage, preuve, bascule (2026-10-05).

Deux passes planifiées (voir `pipeline/collect/address_change.py` pour la
doctrine) :
- `verifier_depuis_les_sites` : lit la page de chaque source active via Tor,
  et les documents récents de la source, à la recherche d'une nouvelle adresse
  annoncée ;
- `verifier_depuis_deepdarkcti` : confronte nos adresses aux listes
  fastfire/deepdarkCTI (`forum.md`, `ransomware_gang.md`), lues sur GitHub en
  clair comme l'import existant.

Une candidate est VÉRIFIÉE avant toute bascule : lue via Tor avec le parser
de la source, elle doit publier des victimes déjà connues pour cette source.
Sinon elle est enregistrée « à examiner », jamais appliquée.

⚠️ La session base est rendue au pool pendant le réseau (`rollback`) : une
passe peut durer de longues minutes et garder une connexion immobiliserait le
pool (piste du ralentissement de l'API pendant les collectes).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.raw_document import RawDocument
from app.db.models.source import Source
from app.db.models.source_address_change import SourceAddressChange
from app.db.session import SessionLocal
from app.pipeline.collect import host_aliases
from app.pipeline.collect.address_change import (
    APPLIED,
    PENDING,
    REJECTED,
    Decision,
    announced_in_documents,
    announced_in_page,
    common_victims,
    compare_with_list,
    current_still_works,
    decide,
    host_of,
    list_suggests_move,
    moved_url,
    parse_deepdarkcti,
)
from app.pipeline.collect.dls.fetch import fetch_dls_html
from app.pipeline.collect.dls.scraper import listing_urls, parse_dls, pick_parser

logger = logging.getLogger(__name__)

DEEPDARKCTI_LISTS = (
    "https://raw.githubusercontent.com/fastfire/deepdarkCTI/main/forum.md",
    "https://raw.githubusercontent.com/fastfire/deepdarkCTI/main/ransomware_gang.md",
)
# Une source dont la dernière collecte réussie date de plus longtemps est
# « en panne » : c'est aussi un motif d'examiner les autres adresses de la liste.
_PERIME_APRES = timedelta(days=3)
# Documents relus pour une annonce de nouvelle adresse.
_FENETRE_DOCUMENTS = timedelta(days=30)
# Coût réseau borné : au plus N candidates vérifiées par source et par passe.
_MAX_CANDIDATES = 3

Fetcher = Callable[[str], str]


# --------------------------------------------------------------------------
# Alias d'hôtes
# --------------------------------------------------------------------------


def alias_depuis_la_base() -> dict[str, str]:
    """{hôte: hôte d'ORIGINE de sa source} pour toutes les bascules appliquées.

    ⚠️ Chaque hôte pointe directement vers l'hôte d'origine, jamais vers le
    précédent : un site qui revient à son ancienne adresse (A -> B -> A) ne
    doit pas créer de boucle."""
    db = SessionLocal()
    try:
        lignes = db.execute(
            select(SourceAddressChange)
            .where(SourceAddressChange.status == APPLIED)
            .order_by(SourceAddressChange.applied_at)
        ).scalars()
        origine: dict[uuid.UUID, str] = {}
        alias: dict[str, str] = {}
        for c in lignes:
            racine = origine.setdefault(c.source_id, host_of(c.old_url))
            for hote in (host_of(c.old_url), host_of(c.new_url)):
                if hote and hote != racine:
                    alias[hote] = racine
        return alias
    finally:
        db.close()


def installer_alias() -> None:
    """À appeler au démarrage de l'API et du worker."""
    host_aliases.configure(alias_depuis_la_base)


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------


def _hotes_connus(db: Session, source: Source) -> set[str]:
    hotes = {host_of(source.url)}
    for c in db.execute(
        select(SourceAddressChange).where(SourceAddressChange.source_id == source.id)
    ).scalars():
        if c.status in (APPLIED,):
            hotes.update({host_of(c.old_url), host_of(c.new_url)})
    return {h for h in hotes if h}


def _deja_decidee(db: Session, source_id: uuid.UUID, hote: str) -> bool:
    """Rejetée par un analyste, ou déjà appliquée : on ne repropose pas."""
    for c in db.execute(
        select(SourceAddressChange).where(SourceAddressChange.source_id == source_id)
    ).scalars():
        if host_of(c.new_url) == hote and c.status in (APPLIED, REJECTED):
            return True
    return False


def _victimes_connues(db: Session, source_id: uuid.UUID) -> list[str]:
    return [
        t
        for (t,) in db.execute(
            select(RawDocument.title)
            .where(RawDocument.source_id == source_id, RawDocument.title.is_not(None))
            .distinct()
            .limit(20_000)
        )
        if t
    ]


def _sources_actives(db: Session) -> list[Source]:
    """Sources .onion actives. Les canaux Telegram et le clearnet n'ont pas
    d'adresse qui déménage de cette façon."""
    return [
        s
        for s in db.execute(select(Source).where(Source.active.is_(True))).scalars()
        if host_of(s.url).endswith(".onion")
    ]


# --------------------------------------------------------------------------
# Vérification d'une candidate
# --------------------------------------------------------------------------


def _juger_page(url: str, page: str) -> bool:
    lues: int | None = None
    if pick_parser(url) is not None and page:
        try:
            lues = len(parse_dls(page, url))
        except Exception:
            lues = 0
    return current_still_works(page, lues)


def _actuelle_fonctionne(url: str, page: str | None, fetch: Fetcher) -> bool:
    """L'adresse actuelle sert-elle encore son contenu ? `page` = déjà lue.

    ⚠️ Une seconde lecture avant de la déclarer hors service : sur Tor, un
    échec isolé est courant (un circuit dégradé n'est pas un déménagement)."""
    if page and _juger_page(url, page):
        return True
    try:
        page = fetch(listing_urls(url)[0])
    except Exception:
        page = ""
    return _juger_page(url, page)


def _verifier(
    url_actuelle: str,
    hote: str,
    connues: list[str],
    fetch: Fetcher,
    actuelle_fonctionne: bool,
) -> tuple[Decision, int | None, int | None]:
    """Lit la candidate via Tor avec le parser de la source. Rien n'est écrit."""
    nouvelle = moved_url(url_actuelle, hote)
    origine = host_aliases.canonical_host(host_of(url_actuelle))
    with host_aliases.temporary({hote: origine}):
        dedie = pick_parser(nouvelle) is not None
        try:
            html = fetch(listing_urls(nouvelle)[0])
        except Exception:
            logger.info("Adresse candidate injoignable : %s", nouvelle, exc_info=True)
            html = ""
        if not html:
            return (
                decide(
                    reachable=False,
                    dedicated_parser=dedie,
                    parsed=0,
                    common=0,
                    current_works=actuelle_fonctionne,
                ),
                None,
                None,
            )
        if not dedie:
            return (
                decide(
                    reachable=True,
                    dedicated_parser=False,
                    parsed=0,
                    common=0,
                    current_works=actuelle_fonctionne,
                ),
                None,
                None,
            )
        try:
            noms = [v.name for v in parse_dls(html, nouvelle)]
        except Exception:
            logger.warning(
                "Parsing de la candidate impossible : %s", nouvelle, exc_info=True
            )
            noms = []
    commun = common_victims(noms, connues)
    return (
        decide(
            reachable=True,
            dedicated_parser=True,
            parsed=len(noms),
            common=commun,
            current_works=actuelle_fonctionne,
        ),
        len(noms),
        commun,
    )


def _enregistrer(
    db: Session,
    source: Source,
    hote: str,
    origine: str,
    preuve: str,
    decision: Decision,
    lues: int | None,
    communes: int | None,
) -> SourceAddressChange:
    maintenant = datetime.now(timezone.utc)
    nouvelle = moved_url(source.url, hote)
    ligne = db.execute(
        select(SourceAddressChange).where(
            SourceAddressChange.source_id == source.id,
            SourceAddressChange.new_url == nouvelle,
        )
    ).scalar_one_or_none()
    if ligne is None:
        ligne = SourceAddressChange(
            id=uuid.uuid4(),
            source_id=source.id,
            old_url=source.url,
            new_url=nouvelle,
            origin=origine,
            detected_at=maintenant,
        )
        db.add(ligne)
    ligne.status = decision.status
    ligne.reason = decision.reason
    ligne.evidence = preuve[:1000]
    ligne.parsed_victims = lues
    ligne.common_victims = communes
    ligne.last_checked_at = maintenant
    if decision.status == APPLIED:
        _basculer(source, ligne, "automatique")
    db.commit()
    if decision.status == APPLIED:
        host_aliases.invalidate()
    return ligne


def _basculer(source: Source, ligne: SourceAddressChange, par: str) -> None:
    ligne.old_url = source.url
    ligne.status = APPLIED
    ligne.applied_at = datetime.now(timezone.utc)
    ligne.decided_by = par
    logger.warning(
        "Source %s : adresse basculée %s -> %s (%s)",
        source.name,
        source.url,
        ligne.new_url,
        par,
    )
    source.url = ligne.new_url


def _traiter_candidates(
    db: Session,
    source: Source,
    candidates: list[tuple[str, str]],
    origine: str,
    fetch: Fetcher,
    bilan: dict,
    page_actuelle: str | None = None,
) -> None:
    """Vérifie au plus `_MAX_CANDIDATES` candidates ; s'arrête à la première
    bascule (la source a alors une nouvelle adresse)."""
    candidates = [(h, p) for h, p in candidates if not _deja_decidee(db, source.id, h)][
        :_MAX_CANDIDATES
    ]
    if not candidates:
        return
    connues = _victimes_connues(db, source.id)
    url_actuelle = source.url
    db.rollback()  # connexion rendue au pool pendant le réseau
    actuelle = _actuelle_fonctionne(url_actuelle, page_actuelle, fetch)
    for hote, preuve in candidates:
        bilan["candidates"] += 1
        decision, lues, communes = _verifier(
            url_actuelle, hote, connues, fetch, actuelle
        )
        ligne = _enregistrer(
            db, source, hote, origine, preuve, decision, lues, communes
        )
        entree = {
            "source": source.name,
            "new_url": ligne.new_url,
            "reason": ligne.reason,
        }
        if decision.status == APPLIED:
            bilan["applied"].append(entree)
            return
        bilan["pending"].append(entree)


# --------------------------------------------------------------------------
# Passes
# --------------------------------------------------------------------------


def _bilan() -> dict:
    return {"sources": 0, "candidates": 0, "applied": [], "pending": [], "errors": 0}


def verifier_depuis_les_sites(db: Session, *, fetch: Fetcher = fetch_dls_html) -> dict:
    """Page de chaque source active (avis de migration) + annonces publiées
    dans ses documents des 30 derniers jours."""
    bilan = _bilan()
    depuis = datetime.now(timezone.utc) - _FENETRE_DOCUMENTS
    for source in _sources_actives(db):
        bilan["sources"] += 1
        connus = _hotes_connus(db, source)
        documents = [
            (t, c)
            for t, c in db.execute(
                select(RawDocument.title, RawDocument.content).where(
                    RawDocument.source_id == source.id,
                    RawDocument.fetched_at >= depuis,
                )
            )
        ]
        candidates: dict[str, str] = {
            a.host: f"annonce publiée par la source : « {a.evidence} »"
            for a in announced_in_documents(documents, connus)
        }
        url, requires_js = source.url, source.requires_js
        db.rollback()  # connexion rendue au pool pendant le réseau
        # ⚠️ Page inconnue (site à rendu JS non lu) = None : on la relira
        # pour juger si l'adresse actuelle fonctionne, jamais « morte » par
        # défaut.
        page: str | None = None
        if not requires_js:
            try:
                page = fetch(listing_urls(url)[0])
            except Exception:
                page = ""
                bilan["errors"] += 1
            for hote in announced_in_page(page, connus):
                candidates.setdefault(hote, "avis de migration servi par le site")
        try:
            _traiter_candidates(
                db, source, list(candidates.items()), "site", fetch, bilan, page
            )
        except Exception:
            db.rollback()
            bilan["errors"] += 1
            logger.exception("Vérification d'adresse en échec : %s", source.name)
    return bilan


def _lire_listes() -> str:
    morceaux = []
    for url in DEEPDARKCTI_LISTS:
        try:
            r = requests.get(
                url, timeout=30, headers={"User-Agent": "threat-intel-platform"}
            )
            r.raise_for_status()
            morceaux.append(r.text)
        except Exception:
            logger.exception("Liste deepdarkCTI indisponible : %s", url)
    return "\n".join(morceaux)


def verifier_depuis_deepdarkcti(
    db: Session,
    *,
    fetch: Fetcher = fetch_dls_html,
    lire_listes: Callable[[], str] = _lire_listes,
    now: datetime | None = None,
) -> dict:
    """Notre adresse n'est plus ONLINE dans la liste (ou notre collecte ne
    réussit plus) et une autre adresse du même nom l'est : on la vérifie."""
    bilan = _bilan()
    texte = lire_listes()
    entrees = parse_deepdarkcti(texte)
    bilan["list_entries"] = len(entrees)
    if not entrees:
        # ⚠️ Liste vide = rien lu (GitHub indisponible ou format changé), pas
        # « tout est à jour » : échec silencieux déjà vécu le 2026-08-22.
        bilan["errors"] += 1
        return bilan
    limite = (now or datetime.now(timezone.utc)) - _PERIME_APRES
    for source in _sources_actives(db):
        bilan["sources"] += 1
        verdict = compare_with_list(entrees, source.name, _hotes_connus(db, source))
        perimee = source.last_collected_at is None or source.last_collected_at < limite
        if not list_suggests_move(verdict, perimee):
            continue
        motif = (
            f"deepdarkCTI : notre adresse est « {verdict.our_status or 'absente'} »"
            + (", collecte en échec depuis plus de 3 jours" if perimee else "")
        )
        candidates = [
            (host_of(e.url), f"{motif} ; « {e.name} » donnée ONLINE")
            for e in verdict.candidates
        ]
        try:
            _traiter_candidates(db, source, candidates, "deepdarkcti", fetch, bilan)
        except Exception:
            db.rollback()
            bilan["errors"] += 1
            logger.exception("Vérification deepdarkCTI en échec : %s", source.name)
    return bilan


# --------------------------------------------------------------------------
# Décisions d'analyste
# --------------------------------------------------------------------------


class AddressChangeError(ValueError):
    pass


def lister(db: Session, limit: int = 100) -> list[tuple[SourceAddressChange, str]]:
    noms = {s.id: s.name for s in db.execute(select(Source)).scalars()}
    lignes = db.execute(
        select(SourceAddressChange)
        .order_by(SourceAddressChange.last_checked_at.desc())
        .limit(limit)
    ).scalars()
    return [(c, noms.get(c.source_id, "?")) for c in lignes]


def appliquer(db: Session, change_id: uuid.UUID, par: str) -> SourceAddressChange:
    """Bascule décidée par un analyste (une candidate « à examiner »)."""
    ligne = db.get(SourceAddressChange, change_id)
    if ligne is None:
        raise AddressChangeError("Changement d'adresse introuvable")
    if ligne.status == APPLIED:
        raise AddressChangeError("Déjà appliqué")
    source = db.get(Source, ligne.source_id)
    if source is None:
        raise AddressChangeError("Source introuvable")
    _basculer(source, ligne, par)
    db.commit()
    host_aliases.invalidate()
    return ligne


def rejeter(db: Session, change_id: uuid.UUID, par: str) -> SourceAddressChange:
    ligne = db.get(SourceAddressChange, change_id)
    if ligne is None:
        raise AddressChangeError("Changement d'adresse introuvable")
    if ligne.status == APPLIED:
        raise AddressChangeError(
            "Déjà appliqué : modifiez l'adresse de la source pour revenir en arrière"
        )
    ligne.status = REJECTED
    ligne.decided_by = par
    db.commit()
    return ligne


__all__ = [
    "PENDING",
    "AddressChangeError",
    "alias_depuis_la_base",
    "appliquer",
    "installer_alias",
    "lister",
    "rejeter",
    "verifier_depuis_deepdarkcti",
    "verifier_depuis_les_sites",
]
