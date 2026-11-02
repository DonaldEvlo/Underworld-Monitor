"""Mesure de notre avance sur les agregateurs (RansomLook, ransomware.live).

    docker compose exec backend python -m app.scripts.measure_lead_time \
        --depuis 2026-09-26T19:00 --resolution 3

LECTURE SEULE en base. Interroge les agregateurs SANS cache (voir
`services/lead_time_service.py`) : compter ~20 min (limite de debit de
ransomware.live).

`--depuis` : debut de la fenetre -- mettre la date a laquelle la collecte
frequente des sites de fuite a commence, sinon la resolution de la collecte
d'avant (2 passes par jour) fausse la mesure.
`--resolution` : periode de collecte des sites de fuite, en heures. Un ecart
inferieur est une egalite.

Chaque chiffre est imprime avec son assiette et ses limites : un pourcentage
sans denominateur n'est pas verifiable.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from statistics import median

from app.db.session import SessionLocal
from app.pipeline.evaluation.lead_time import is_eligible, summarize
from app.services.lead_time_service import (
    RANSOMLOOK,
    RANSOMWARE_LIVE,
    fresh_indexes,
    measure,
    our_victims,
)


def _date(valeur: str) -> datetime:
    d = datetime.fromisoformat(valeur)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _h(valeur: float | None) -> str:
    if valeur is None:
        return "n/d"
    return f"{valeur:+.1f} h" if abs(valeur) < 72 else f"{valeur / 24:+.1f} j"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--depuis", type=_date, required=True)
    parser.add_argument("--resolution", type=float, default=3.0)
    args = parser.parse_args()
    maintenant = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        victimes, premieres = our_victims(db)
    finally:
        db.close()

    gangs = {
        v.gang
        for v in victimes
        if v.source in premieres and is_eligible(v, premieres[v.source], args.depuis)
    }
    print(
        f"Fenetre : {args.depuis:%Y-%m-%d %H:%M} UTC -> {maintenant:%Y-%m-%d %H:%M} UTC"
    )
    print(
        f"Resolution de notre collecte : {args.resolution:g} h (ecart plus petit = egalite)"
    )
    print(f"Gangs a interroger : {len(gangs)} ({', '.join(sorted(gangs)) or 'aucun'})")
    index = fresh_indexes(gangs) if gangs else {}
    indisponibles = sorted(f"{o}/{g}" for (o, g), i in index.items() if i is None)
    non_suivis = sorted(f"{o}/{g}" for (o, g), i in index.items() if i == {})

    observations, compteurs = measure(
        victimes, premieres, index, args.depuis, maintenant
    )
    print(
        f"\nVictimes connues : {compteurs['total']} | exclues (rattrapage ou hors "
        f"fenetre) : {compteurs['rattrapage_ou_hors_fenetre']} | rattrapage tardif "
        f"(deja indexees avant notre 1re collecte) : {compteurs['rattrapage_tardif']}"
        f" | ELIGIBLES : "
        f"{compteurs['eligibles']}"
    )
    if non_suivis:
        print(f"Gangs non suivis (exclus de la mesure) : {', '.join(non_suivis)}")
    if indisponibles:
        print(f"Observateurs sans reponse (exclus) : {', '.join(indisponibles)}")

    for observateur in (RANSOMLOOK, RANSOMWARE_LIVE):
        s = summarize(observations, observateur, args.resolution)
        print(f"\n== {observateur} : {s.eligible} victime(s) confrontee(s)")
        if not s.eligible:
            continue
        print(
            f"  mesurees {s.measured} : AVANCE {s.ahead} | egalite {s.tied} | "
            f"retard {s.behind} | ecart median {_h(s.median_lead_hours)} (>0 = nous avant)"
        )
        print(
            f"  pas encore indexees chez lui : {s.censored} (avance d'AU MOINS "
            f"{_h(s.median_censored_lower_bound_hours)} en mediane)"
        )
        for source, ecarts in sorted(s.by_source.items(), key=lambda x: -len(x[1])):
            print(
                f"    {source[:34]:34} n={len(ecarts):3} mediane {_h(median(ecarts))}"
            )
        # Les victimes OU NOUS SOMMES EN AVANCE, nominatives : ce sont les cas
        # citables, et ils doivent pouvoir etre reverifies un par un (date
        # d'indexation declaree par l'agregateur contre notre passage de
        # collecte).
        avances = sorted(
            (
                o
                for o in observations
                if o.observer == observateur
                and o.lead_hours is not None
                and o.lead_hours > args.resolution
            ),
            key=lambda o: -(o.lead_hours or 0),
        )
        if avances:
            print(f"    -- EN AVANCE ({len(avances)}) --")
        for o in avances:
            print(
                f"    avance {_h(o.lead_hours):>9} : {o.victim.terms[0][:38]:38} "
                f"({o.victim.source[:18]:18} gang={o.victim.gang[:12]:12} "
                f"nous {o.victim.first_seen:%d/%m %H:%M} -> lui "
                f"{o.indexed_at:%d/%m %H:%M})"
            )
        # Les victimes qu'il n'a PAS indexees portent toute avance eventuelle :
        # nominatives, pour etre verifiees a la main (un rapprochement manque
        # passerait pour une avance).
        for o in observations:
            if o.observer == observateur and o.censored:
                print(
                    f"    non indexee : {o.victim.terms[0][:40]:40} "
                    f"({o.victim.source[:20]}, vue le {o.victim.first_seen:%Y-%m-%d %H:%M})"
                )

    print(
        "\nLIMITES : notre « premiere vue » est la date du passage de collecte, pas "
        "de la publication ; « discovered » est la date d'indexation declaree par "
        "l'agregateur ; un petit nombre de victimes eligibles ne permet pas de "
        "generaliser -- citer n avec chaque chiffre."
    )


if __name__ == "__main__":
    main()
