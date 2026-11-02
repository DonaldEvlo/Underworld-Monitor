"""Avance ou retard de notre detection sur les agregateurs (RansomLook,
ransomware.live), victime par victime. Logique PURE : ni base, ni reseau.

Question posee : quand une victime apparait sur un site de fuite, la voyons-
nous AVANT que les agregateurs publics ne l'indexent ? C'est la seule valeur
ajoutee de lire les sites nous-memes plutot que de consommer leur flux.

⚠️ TROIS BIAIS, NEUTRALISES ICI -- chacun ferait mentir le chiffre :

1. LE RATTRAPAGE D'HISTORIQUE. A la premiere collecte d'une source, TOUTES ses
   victimes anciennes sont « vues pour la premiere fois » ce jour-la ; les
   agregateurs les connaissent depuis des mois. Mesure du 2026-09-15 : ecart
   median -329 j, entierement du a cet effet. → Une victime ne compte que si
   sa source etait DEJA collectee avant elle (`ELIGIBILITY_MARGIN` apres la
   premiere collecte de la source) et si elle entre dans la fenetre mesuree.

2. LA VICTIME ENCORE ABSENTE CHEZ L'AGREGATEUR. Elle n'est ni « pas
   appariee » ni « en retard » : nous avons au moins `maintenant - premiere
   vue` d'avance. C'est une observation CENSUREE (au sens statistique), comptee
   a part et jamais melee a la mediane des ecarts mesures.

3. LA RESOLUTION DE NOTRE COLLECTE. Notre date de premiere vue est celle du
   passage de collecte, pas celle de la publication : a une passe toutes les
   3 h, un ecart inferieur a la periode n'est pas significatif. L'appelant
   fournit la periode ; les ecarts sous ce seuil sont classes « egalite ».

⚠️ Le rapprochement reutilise EXACTEMENT les cles de la corroboration
(`domain_candidates`, `name_key`) : egalite apres normalisation, jamais
inclusion, et par nom seulement au sein du meme gang (index par gang).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median

from app.pipeline.enrich.ransomlook_corroboration import (
    _parse_discovered,
    domain_candidates,
    name_key,
)

# Une victime vue moins d'une heure apres la toute premiere collecte de sa
# source fait partie du rattrapage, pas d'une publication nouvelle.
ELIGIBILITY_MARGIN = timedelta(hours=1)


@dataclass(frozen=True)
class OurVictim:
    source: str
    gang: str
    first_seen: datetime
    # Titre, domaine et raison sociale connus pour cette victime.
    terms: tuple[str, ...]


@dataclass(frozen=True)
class LeadObservation:
    victim: OurVictim
    observer: str
    indexed_at: datetime | None
    # Positif = NOUS avant l'agregateur. None si la victime est absente chez
    # lui (observation censuree, voir `lower_bound_hours`).
    lead_hours: float | None
    lower_bound_hours: float | None = None

    @property
    def censored(self) -> bool:
        return self.indexed_at is None


def _as_utc(valeur: datetime | str | None) -> datetime | None:
    date = valeur if isinstance(valeur, datetime) else _parse_discovered(valeur)
    if date is not None and date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date


def _cles(texte: str) -> set[str]:
    cles = {f"d:{d}" for d in domain_candidates(texte)}
    nom = name_key(texte)
    if nom:
        cles.add(f"n:{nom}")
    return cles


def build_index(annonces: Iterable[dict]) -> dict[str, datetime]:
    """Index {cle -> PREMIERE date d'indexation} d'un gang chez un observateur.

    `annonces` : forme commune des deux parseurs, `{post_title, discovered}`.
    Une annonce sans date est ignoree : elle ne peut pas dater une avance."""
    index: dict[str, datetime] = {}
    for annonce in annonces:
        date = _as_utc(annonce.get("discovered"))
        titre = (annonce.get("post_title") or "").strip()
        if date is None or not titre:
            continue
        for cle in _cles(titre):
            if cle not in index or date < index[cle]:
                index[cle] = date
    return index


def first_indexed(terms: Iterable[str], index: dict[str, datetime]) -> datetime | None:
    dates = [index[c] for t in terms if t for c in _cles(t) if c in index]
    return min(dates) if dates else None


def is_eligible(
    victim: OurVictim, source_first_collection: datetime, window_start: datetime
) -> bool:
    """Victime NOUVELLE (pas du rattrapage) et dans la fenetre mesuree."""
    return (
        victim.first_seen >= window_start
        and victim.first_seen >= source_first_collection + ELIGIBILITY_MARGIN
    )


def existed_before_collection(
    victim: OurVictim,
    indexes: Iterable[dict[str, datetime]],
    source_first_collection: datetime,
) -> bool:
    """La victime etait-elle DEJA indexee avant notre premiere collecte du site ?

    ⚠️ RATTRAPAGE TARDIF, mis au jour par la premiere mesure reelle
    (2026-09-26) : AKIRA donnait un ecart median de -401 JOURS, DIRE WOLF de
    -29 j. Ce ne sont pas des retards : ces sites n'exposent pas toute leur
    liste a chaque passage, si bien que des victimes anciennes nous
    apparaissent « pour la premiere fois » bien apres le debut de la
    collecte. Le filtre sur notre seule premiere vue ne les voit pas. Un
    agregateur qui les a indexees AVANT notre premiere collecte prouve
    qu'elles existaient deja : elles sont exclues, pour TOUS les
    observateurs (la population comparee doit etre la meme)."""
    for index in indexes:
        date = first_indexed(victim.terms, index)
        if date is not None and date < source_first_collection:
            return True
    return False


def observe(
    victim: OurVictim, observer: str, index: dict[str, datetime], now: datetime
) -> LeadObservation:
    indexe = first_indexed(victim.terms, index)
    if indexe is None:
        return LeadObservation(
            victim,
            observer,
            None,
            None,
            lower_bound_hours=(now - victim.first_seen).total_seconds() / 3600,
        )
    return LeadObservation(
        victim, observer, indexe, (indexe - victim.first_seen).total_seconds() / 3600
    )


@dataclass
class LeadSummary:
    observer: str
    eligible: int = 0
    measured: int = 0
    ahead: int = 0
    tied: int = 0
    behind: int = 0
    censored: int = 0
    median_lead_hours: float | None = None
    median_censored_lower_bound_hours: float | None = None
    by_source: dict[str, list[float]] = field(default_factory=dict)


def summarize(
    observations: list[LeadObservation], observer: str, resolution_hours: float
) -> LeadSummary:
    """Bilan pour un observateur. Un ecart dont la valeur absolue ne depasse
    pas la resolution de notre collecte est une EGALITE, pas une avance."""
    obs = [o for o in observations if o.observer == observer]
    s = LeadSummary(observer=observer, eligible=len(obs))
    ecarts = [o.lead_hours for o in obs if o.lead_hours is not None]
    bornes = [
        o.lower_bound_hours
        for o in obs
        if o.censored and o.lower_bound_hours is not None
    ]
    s.measured = len(ecarts)
    s.censored = len(bornes)
    s.ahead = sum(1 for e in ecarts if e > resolution_hours)
    s.behind = sum(1 for e in ecarts if e < -resolution_hours)
    s.tied = s.measured - s.ahead - s.behind
    s.median_lead_hours = median(ecarts) if ecarts else None
    s.median_censored_lower_bound_hours = median(bornes) if bornes else None
    for o in obs:
        if o.lead_hours is not None:
            s.by_source.setdefault(o.victim.source, []).append(o.lead_hours)
    return s
