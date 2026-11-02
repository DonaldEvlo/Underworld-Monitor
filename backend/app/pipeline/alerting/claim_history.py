"""Historique des revendications d'une victime : republication ou attribution
disputee (plan de credibilite, phase 4, revue le 2026-09-30).

Mesure qui a fonde ce module (2026-09-30) : sur 123 detections revendiquees
par >= 2 gangs, deux phenomenes DISTINCTS -- et aucun ne dit « la fuite est
peut-etre fausse » :

- RECYCLAGE. ORION compte 14 victimes, dont 13 deja publiees par LockBit 3.0,
  LockBit TOUJOURS premier, jusqu'a trois ans avant (transitaire-exemple.com :
  2023-09-16 chez LockBit, 2026-08-05 chez ORION). lockbit3 -> qilin : 5 sur 5
  dans le meme sens. La fuite est reelle ; c'est sa NOUVEAUTE qui est fausse.
- ATTRIBUTION DISPUTEE. beast + qilin : 4 victimes communes, toutes publiees a
  moins de 7 jours d'ecart. L'incident est probablement reel ; c'est l'AUTEUR
  qui est incertain (affilie travaillant pour deux programmes, donnees
  partagees).

⚠️ La premiere version (commit 8fa52a4, jamais pousse) classait ces deux cas
« douteuse » : sur transitaire-exemple.com -- vraie victime LockBit de 2023 -- le
produit aurait laisse entendre que la fuite etait peut-etre fausse. Meme faute
de vocabulaire que « l'organisation Krybit a confirme ». Un qualificatif
decrit ce qui est observe ; il ne change pas le niveau de credibilite.

⚠️ Dates de PUBLICATION par chaque gang (`discovered` chez ransomware.live),
jamais `attackdate` : chez certains gangs c'est une date d'import en lot
(voir `ransomware_live.batch_indexing_dates`).

⚠️ Une date inconnue pour NOTRE gang = aucune conclusion (absence de mesure,
pas absence de republication). Un autre gang publie plus TARD que nous : c'est
lui qui republie, rien a dire sur notre revendication.

Logique pure : aucune base, aucun reseau.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Meme fenetre que la fraicheur de la gravite : la couverture du flux
# RansomLook, soit la definition de « recent » dans cet ecosysteme. A moins de
# 30 jours d'ecart, deux publications sont contemporaines (dispute) ; au-dela,
# la plus tardive republie la plus ancienne.
REPUBLICATION_GAP_DAYS = 30


@dataclass(frozen=True)
class ClaimHistory:
    # (gang, date) de la plus ANCIENNE revendication d'un autre gang, anterieure
    # a la notre de plus de REPUBLICATION_GAP_DAYS.
    republished_from: tuple[str, datetime] | None = None
    # Autres gangs ayant publie la meme victime a moins de
    # REPUBLICATION_GAP_DAYS de nous.
    disputed_with: tuple[str, ...] = ()


def classify_claims(
    own_gang: str, first_seen: dict[str, datetime | None]
) -> ClaimHistory:
    """Situe NOTRE revendication (celle du site d'ou vient le document) par
    rapport aux autres gangs qui publient la meme victime.

    `first_seen` : gang -> date de premiere publication de cette victime chez
    ce gang (None = inconnue). Les noms de gang sont deja normalises par
    l'appelant."""
    own = first_seen.get(own_gang)
    if own is None:
        return ClaimHistory()
    ecart = timedelta(days=REPUBLICATION_GAP_DAYS)
    plus_ancienne: tuple[str, datetime] | None = None
    disputes: list[str] = []
    for gang, date in first_seen.items():
        if gang == own_gang or date is None:
            continue
        if date < own - ecart:
            if plus_ancienne is None or date < plus_ancienne[1]:
                plus_ancienne = (gang, date)
        elif abs(date - own) <= ecart:
            disputes.append(gang)
    return ClaimHistory(plus_ancienne, tuple(sorted(disputes)))
