"""Validation de l'echelle de credibilite contre un etalon EXTERIEUR
(plan de credibilite, phase 6).

Question : le statut affiche par le site du gang (« publiee » / « en
attente ») PREDIT-il qu'une source exterieure confirmera l'incident ?
L'etalon est la couverture presse indexee par ransomware.live.

⚠️ CE QUI NE PEUT PAS ETRE VALIDE ICI. La presse est a la fois un niveau de
l'echelle (`confirmed`) et l'etalon : valider `confirmed` contre la presse
serait circulaire. On ne valide que les AUTRES signaux.

⚠️ LIMITES DE L'ETALON, a ecrire avec chaque resultat :
  - etiquette POSITIVE seulement : l'absence de presse ne prouve rien ;
  - elle arrive AVEC RETARD : une victime recente n'a pas encore eu le temps
    d'etre couverte ;
  - elle est biaisee vers les GRANDES organisations et les gangs
    mediatises -- d'ou la stratification par gang (Mantel-Haenszel), sans
    laquelle un « effet LockBit » se lirait comme un effet du statut.
  - le statut est observe AUJOURD'HUI, la presse a pu paraitre avant : c'est
    une association, pas une prediction au sens temporel.

Logique pure : aucune base, aucun reseau.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from app.pipeline.evaluation.gold import wilson

STATUTS = ("published", "pending", "unknown")


@dataclass(frozen=True)
class Observation:
    """Une victime de nos sites de fuite, appariee a ransomware.live."""

    gang: str
    status: str  # published / pending / unknown
    press: bool


@dataclass(frozen=True)
class Ligne:
    status: str
    total: int
    press: int
    ci_low: float
    ci_high: float

    @property
    def rate(self) -> float:
        return self.press / self.total if self.total else 0.0


def tableau(observations: list[Observation]) -> list[Ligne]:
    """Taux de confirmation par la presse, par statut, avec intervalle de
    Wilson a 95 %."""
    compte: dict[str, list[int]] = {s: [0, 0] for s in STATUTS}
    for o in observations:
        ligne = compte.setdefault(o.status, [0, 0])
        ligne[0] += 1
        ligne[1] += int(o.press)
    return [
        Ligne(s, n, k, *wilson(k, n))
        for s, (n, k) in compte.items()
        if n or s in STATUTS
    ]


def _log_comb(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """p-valeur bilaterale du test exact de Fisher sur le tableau 2x2
    [[a, b], [c, d]] (somme des probabilites hypergeometriques inferieures
    ou egales a celle du tableau observe).

    Choisi plutot qu'un khi-deux parce que les effectifs attendus sont
    petits (3 victimes « en attente » couvertes par la presse)."""
    ligne1, ligne2, col1 = a + b, c + d, a + c
    n = ligne1 + ligne2
    if n == 0:
        return 1.0
    bas, haut = max(0, col1 - ligne2), min(col1, ligne1)

    def log_p(x: int) -> float:
        return _log_comb(ligne1, x) + _log_comb(ligne2, col1 - x) - _log_comb(n, col1)

    observe = log_p(a)
    total = sum(
        math.exp(log_p(x)) for x in range(bas, haut + 1) if log_p(x) <= observe + 1e-9
    )
    return min(1.0, total)


def mantel_haenszel(observations: list[Observation]) -> dict:
    """Rapport de cotes « publiee contre non publiee » AJUSTE sur le gang.

    Chaque gang forme une strate ; les strates sans contraste (toutes
    publiees, ou aucune presse) ne portent aucune information et sont
    comptees a part. `None` si aucune strate n'est informative -- on ne
    fabrique pas de chiffre."""
    strates: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for o in observations:
        if o.status == "unknown":
            continue  # ni expose, ni non expose : hors du contraste
        publiee = o.status == "published"
        # a = publiee & presse, b = publiee sans presse,
        # c = non publiee & presse, d = non publiee sans presse
        i = (0 if o.press else 1) if publiee else (2 if o.press else 3)
        strates[o.gang][i] += 1

    somme_r = somme_s = 0.0
    somme_pr = somme_ps_qr = somme_qs = 0.0
    informatives = []
    for gang, (a, b, c, d) in strates.items():
        n = a + b + c + d
        if n == 0 or (a + b) == 0 or (c + d) == 0 or (a + c) == 0:
            continue
        r, s = a * d / n, b * c / n
        p, q = (a + d) / n, (b + c) / n
        somme_r += r
        somme_s += s
        somme_pr += p * r
        somme_ps_qr += p * s + q * r
        somme_qs += q * s
        informatives.append(gang)
    if not (somme_r and somme_s):
        return {
            "odds_ratio": None,
            "ci_low": None,
            "ci_high": None,
            "strates_informatives": sorted(informatives),
            "strates_total": len(strates),
            "detail": {g: tuple(v) for g, v in strates.items()},
        }
    ratio = somme_r / somme_s
    # Variance de ln(OR) de Robins-Breslow-Greenland : sans intervalle, un
    # rapport de cotes calcule sur une poignee de cas se lirait comme un
    # resultat.
    variance = (
        somme_pr / (2 * somme_r**2)
        + somme_ps_qr / (2 * somme_r * somme_s)
        + somme_qs / (2 * somme_s**2)
    )
    marge = 1.96 * math.sqrt(variance)
    return {
        "odds_ratio": ratio,
        "ci_low": math.exp(math.log(ratio) - marge),
        "ci_high": math.exp(math.log(ratio) + marge),
        "strates_informatives": sorted(informatives),
        "strates_total": len(strates),
        # (publiee & presse, publiee sans, non publiee & presse, non publiee sans)
        "detail": {g: tuple(v) for g, v in strates.items()},
    }
