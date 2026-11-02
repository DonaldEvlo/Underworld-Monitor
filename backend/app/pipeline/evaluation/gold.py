"""Echantillon de reference : tirage stratifie et mesures (logique pure).

Repond a la question restee ouverte depuis la creation du classifieur
d'annonces : **les regles ont-elles raison ?** Et, a partir de la, le LLM et
le modele font-ils mieux qu'elles ?

**Composition, et pourquoi elle n'est pas proportionnelle.** Un tirage
purement aleatoire donnerait surtout des `leak` et presque aucun `noise`, ou se
joue pourtant l'erreur la plus couteuse : une victime ecartee ne remonte
jamais. On sur-echantillonne donc `noise`, puis on REDRESSE les estimations
par le poids de chaque strate (`stratum_population / tires`). Les deux
chiffres -- brut sur l'echantillon, redresse sur le corpus -- sont rendus :
le premier dit ce qu'on a observe, le second ce qu'il en decoule pour le
corpus entier.

**Deux types de source, mesures separement.** Sur un site de fuite, un
document EST une victime ; sur un forum, il faut juger l'annonce. Melanger les
deux ferait passer la facilite des sites de fuite pour une qualite des regles
sur les forums, qui sont le vrai point faible.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field

VERDICTS = ("leak", "noise", "uncertain")
KINDS = ("victim_site", "forum")

# Reprise de la repartition calibree le 2026-08-29 (intervalles de Wilson) :
# a n=100 la marge sur `noise` tombe a +/- 7 points.
DEFAULT_QUOTAS = {"leak": 60, "noise": 100, "uncertain": 40}
DEFAULT_CONTROL_SIZE = 50
# Graine fixe : deux tirages sur le meme corpus donnent le meme echantillon.
DEFAULT_SEED = 42


@dataclass(frozen=True)
class Candidate:
    document_id: str
    kind: str
    verdict: str


@dataclass(frozen=True)
class SampledItem:
    document_id: str
    rank: int
    control_rank: int | None
    stratum: str
    stratum_population: int
    sampled_verdict: str


def stratum_of(kind: str, verdict: str) -> str:
    return f"{kind}:{verdict}"


def _split_quota(quota: int, available: dict[str, int]) -> dict[str, int]:
    """Repartit le quota d'un verdict a parts egales entre les deux types de
    source ; ce qu'un type ne peut pas fournir est reporte sur l'autre.

    Cas reel : il n'existe quasiment aucun `noise` sur les sites de fuite (deux
    documents, un concours publie par LockBit). Sans report, le quota `noise`
    serait ampute de moitie."""
    share = {kind: min(quota // 2, available.get(kind, 0)) for kind in KINDS}
    reste = quota - sum(share.values())
    for kind in KINDS:
        extra = min(reste, available.get(kind, 0) - share[kind])
        share[kind] += extra
        reste -= extra
    return share


def draw_sample(
    candidates: list[Candidate],
    quotas: dict[str, int] | None = None,
    control_size: int = DEFAULT_CONTROL_SIZE,
    seed: int = DEFAULT_SEED,
) -> list[SampledItem]:
    """Tire l'echantillon stratifie (verdict des regles x type de source).

    L'ordre de presentation est MELANGE : presenter les `noise` a la suite
    installerait une attente chez l'annotateur. Le sous-ensemble de controle
    recoit un second ordre, different."""
    quotas = quotas or DEFAULT_QUOTAS
    rng = random.Random(seed)

    par_strate: dict[str, list[Candidate]] = defaultdict(list)
    for cand in sorted(candidates, key=lambda c: c.document_id):
        par_strate[stratum_of(cand.kind, cand.verdict)].append(cand)

    tires: list[tuple[Candidate, str]] = []
    for verdict, quota in quotas.items():
        available = {k: len(par_strate[stratum_of(k, verdict)]) for k in KINDS}
        for kind, n in _split_quota(quota, available).items():
            strate = stratum_of(kind, verdict)
            tires.extend((c, strate) for c in rng.sample(par_strate[strate], n))

    rng.shuffle(tires)
    controle = rng.sample(range(len(tires)), min(control_size, len(tires)))
    rang_controle = {index: rang for rang, index in enumerate(controle, start=1)}

    return [
        SampledItem(
            document_id=cand.document_id,
            rank=index + 1,
            control_rank=rang_controle.get(index),
            stratum=strate,
            stratum_population=len(par_strate[strate]),
            sampled_verdict=cand.verdict,
        )
        for index, (cand, strate) in enumerate(tires)
    ]


# --------------------------------------------------------------------------
# Mesures
# --------------------------------------------------------------------------


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance a 95 % d'une proportion (Wilson).

    Rendu parce qu'une justesse de 85 % mesuree sur 60 items a un intervalle
    reel d'environ 74-92 % : sans lui, deux chiffres proches se liraient comme
    une difference."""
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    centre = p + z * z / (2 * total)
    marge = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    denom = 1 + z * z / total
    return (max(0.0, (centre - marge) / denom), min(1.0, (centre + marge) / denom))


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Accord corrige du hasard entre deux annotations des memes items.

    `None` quand il n'est pas defini (aucune paire, ou une seule etiquette
    employee des deux cotes) -- plutot qu'un 1.0 trompeur."""
    if not pairs:
        return None
    total = len(pairs)
    observe = sum(1 for a, b in pairs if a == b) / total
    labels = {label for pair in pairs for label in pair}
    attendu = sum(
        (sum(1 for a, _ in pairs if a == lab) / total)
        * (sum(1 for _, b in pairs if b == lab) / total)
        for lab in labels
    )
    if attendu >= 1.0:
        return None
    return (observe - attendu) / (1 - attendu)


@dataclass(frozen=True)
class Judged:
    """Un item annote, et ce qu'en dit un classifieur."""

    human: str
    predicted: str | None  # None = ce classifieur ne s'est pas prononce
    kind: str
    weight: float = 1.0


@dataclass
class Rate:
    """Une proportion, brute et redressee."""

    hits: int
    total: int
    weighted: float | None
    ci_low: float
    ci_high: float

    @property
    def raw(self) -> float | None:
        return self.hits / self.total if self.total else None


def _rate(items: list[Judged], selected, succeeded) -> Rate:
    base = [i for i in items if selected(i)]
    hits = [i for i in base if succeeded(i)]
    poids = sum(i.weight for i in base)
    low, high = wilson(len(hits), len(base))
    return Rate(
        hits=len(hits),
        total=len(base),
        weighted=(sum(i.weight for i in hits) / poids) if poids else None,
        ci_low=low,
        ci_high=high,
    )


@dataclass
class Report:
    judged: int
    abstained: int
    human_uncertain: int
    accuracy: Rate
    # ⚠️ LA mesure du risque : parmi les vraies fuites, combien ne sont PAS
    # ecartees. `uncertain` compte comme conserve -- il alimente la detection.
    victim_retention: Rate
    leak_precision: Rate
    noise_filtering: Rate
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    costly: int = 0


def evaluate(items: list[Judged]) -> Report:
    """Confronte un classifieur a l'annotation humaine.

    Les items que l'humain juge `uncertain` sont EXCLUS des taux : on ne peut
    pas reprocher a un classifieur de mal trancher ce qu'un humain ne sait pas
    trancher. Ils sont comptes a part."""
    prononces = [i for i in items if i.predicted is not None]
    tranches = [i for i in prononces if i.human != "uncertain"]

    confusion = {p: {h: 0 for h in VERDICTS} for p in VERDICTS}
    for item in prononces:
        if item.predicted in confusion and item.human in VERDICTS:
            confusion[item.predicted][item.human] += 1

    return Report(
        judged=len(prononces),
        abstained=len(items) - len(prononces),
        human_uncertain=sum(1 for i in prononces if i.human == "uncertain"),
        accuracy=_rate(tranches, lambda i: True, lambda i: i.predicted == i.human),
        victim_retention=_rate(
            tranches, lambda i: i.human == "leak", lambda i: i.predicted != "noise"
        ),
        leak_precision=_rate(
            tranches, lambda i: i.predicted == "leak", lambda i: i.human == "leak"
        ),
        noise_filtering=_rate(
            tranches, lambda i: i.human == "noise", lambda i: i.predicted == "noise"
        ),
        confusion=confusion,
        costly=sum(1 for i in tranches if i.human == "leak" and i.predicted == "noise"),
    )


def weights_by_stratum(
    strata: list[str], populations: dict[str, int]
) -> dict[str, float]:
    """Poids de redressement : combien de documents du corpus chaque item
    represente dans sa strate."""
    tires = Counter(strata)
    return {s: populations[s] / n for s, n in tires.items() if n}
