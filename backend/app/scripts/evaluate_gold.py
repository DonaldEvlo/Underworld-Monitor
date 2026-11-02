"""Mesure les regles, la cascade regles + LLM et le modele contre la
reference annotee a la main (table `gold_annotations`).

    docker compose exec backend python -m app.scripts.evaluate_gold
    docker compose exec backend python -m app.scripts.evaluate_gold --partial

`--partial` autorise la mesure avant la fin de la passe principale. A reserver
aux verifications techniques : lire des resultats a mi-parcours oriente la
suite de l'annotation.

Deux chiffres par taux, et les deux comptent :
  - BRUT     : ce qu'on a observe sur l'echantillon, avec son intervalle a 95 % ;
  - REDRESSE : ce qu'il en decoule pour le corpus entier, chaque item pesant le
               nombre de documents de sa strate qu'il represente.

Remplace `build_gold_sample.py` / `score_gold.py` (fichiers CSV, titre seul,
jamais annotes).
"""

from __future__ import annotations

import argparse
import sys

from app.db.session import SessionLocal
from app.services import gold_service
from app.services.gold_service import GoldError

NOMS = {
    "rules": "REGLES (rejouees)",
    "rules_llm": "REGLES + LLM sur les `uncertain`",
}
PORTEES = {"all": "tout", "victim_site": "sites de fuite", "forum": "forums"}
TAUX = [
    ("accuracy", "justesse"),
    ("victim_retention", "victimes conservees"),
    ("leak_precision", "precision `leak`"),
    ("noise_filtering", "bruit ecarte"),
]


def _pct(x: float | None) -> str:
    return "  -  " if x is None else f"{100 * x:5.1f}"


def _ligne(nom: str, rate: dict) -> str:
    if not rate["total"]:
        return f"    {nom:<22} (aucun item)"
    brut = rate["hits"] / rate["total"]
    return (
        f"    {nom:<22} brut {_pct(brut)} %  [{_pct(rate['ci_low'])}-{_pct(rate['ci_high'])}]"
        f"  n={rate['total']:<4} redresse {_pct(rate['weighted'])} %"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--max-disagreements", type=int, default=40)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        try:
            res = gold_service.evaluate_gold(db, allow_partial=args.partial)
        except GoldError as exc:
            print(f"Refuse : {exc}")
            return 1
        desaccords = gold_service.disagreements(db)
    finally:
        db.close()

    p = res["progress"]
    print(
        f"Reference : {p['annotated']}/{p['total']} annotes, "
        f"controle {p['control_annotated']}/{p['control_total']}"
    )

    for cle, bloc in res["classifiers"].items():
        print("\n" + "=" * 78)
        print(NOMS[cle])
        print("=" * 78)
        for portee, libelle in PORTEES.items():
            rep = bloc[portee]
            if not rep["judged"]:
                print(f"  [{libelle}] aucun item juge par ce classifieur")
                continue
            print(
                f"  [{libelle}] {rep['judged']} items, {rep['human_uncertain']} indecidables "
                f"(exclus des taux), {rep['abstained']} sans verdict"
            )
            for champ, nom in TAUX:
                print(_ligne(nom, rep[champ]))
            print(f"    victimes ECARTEES A TORT : {rep['costly']}")

    cov = res["llm_coverage"]
    print(
        f"\nCouverture LLM : {cov['arbitrated_by_llm']} des "
        f"{cov['uncertain_by_rules']} `uncertain` des regles ont un verdict LLM."
    )

    k = res["annotator_consistency"]
    print("\n" + "=" * 78)
    print(f"COHERENCE DE L'ANNOTATEUR ({k['pairs']} documents rejuges)")
    print("=" * 78)
    if k["pairs"]:
        kappa = "non defini" if k["kappa"] is None else f"{k['kappa']:.2f}"
        print(f"  accord brut {_pct(k['raw_agreement'])} %   kappa de Cohen {kappa}")
        print(
            "  lecture : < 0,40 faible · 0,40-0,60 moyen · 0,60-0,80 bon · > 0,80 excellent"
        )
    else:
        print("  passe de controle non faite")

    print("\n" + "=" * 78)
    print(
        f"DESACCORDS REGLES / HUMAIN : {len(desaccords)}  (victimes ecartees en tete)"
    )
    print("=" * 78)
    for d in desaccords[: args.max_disagreements]:
        marque = "!!" if d["costly"] else "  "
        print(
            f"{marque} #{d['rank']:<4} humain={d['human']:<9} regles={d['rules']:<9} "
            f"[{(d['reason'] or '')[:32]}]"
        )
        print(f"         {(d['title'] or '')[:70]}  ({d['source'][:24]})")
        if d["note"]:
            print(f"         note : {d['note'][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
