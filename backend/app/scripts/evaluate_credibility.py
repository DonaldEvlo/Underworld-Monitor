"""Validation de l'echelle de credibilite contre la presse (phase 6).

    docker compose exec backend python -m app.scripts.evaluate_credibility

LECTURE SEULE : n'ecrit rien en base. Seul appel reseau : l'historique
ransomware.live de chaque gang, deja en cache 24 h par la corroboration.

Question : le statut affiche par le site du gang (« publiee » / « en
attente ») s'associe-t-il a une confirmation EXTERIEURE (presse) ?

⚠️ Les limites de l'etalon sont imprimees avec les resultats : un chiffre
sans ses limites se lirait comme une preuve. Voir
`pipeline/evaluation/credibility_eval.py`.
"""

from __future__ import annotations

import sys

from app.db.session import SessionLocal
from app.pipeline.evaluation.credibility_eval import (
    fisher_exact,
    mantel_haenszel,
    tableau,
)
from app.services.credibility_service import observations_for_validation

LIBELLES = {"published": "publiee", "pending": "en attente", "unknown": "inconnu"}


def main() -> int:
    db = SessionLocal()
    try:
        observations, couverture = observations_for_validation(db)
    finally:
        db.close()

    print("=" * 78)
    print("VALIDATION DE L'ECHELLE DE CREDIBILITE -- etalon : presse (ransomware.live)")
    print("=" * 78)
    print(
        f"Victimes de nos sites de fuite : {couverture['victimes']} | appariees : "
        f"{len(observations)} | non appariees : {couverture['non_appariees']}"
    )
    if couverture["gangs_indisponibles"]:
        print(f"Gangs sans historique disponible : {couverture['gangs_indisponibles']}")
    confirmees = sum(o.press for o in observations)
    print(f"Victimes confirmees par la presse : {confirmees}")

    print("\nTaux de confirmation par la presse, selon le statut affiche :")
    lignes = {line.status: line for line in tableau(observations)}
    for statut in ("published", "pending", "unknown"):
        line = lignes[statut]
        print(
            f"  {LIBELLES[statut]:<11} {line.press:4}/{line.total:<5} "
            f"{100 * line.rate:5.1f} %  IC95 [{100 * line.ci_low:4.1f}-{100 * line.ci_high:4.1f}]"
        )

    pub, att = lignes["published"], lignes["pending"]
    p = fisher_exact(pub.press, pub.total - pub.press, att.press, att.total - att.press)
    print(f"\nPubliee contre en attente -- test exact de Fisher : p = {p:.3f}")

    mh = mantel_haenszel(observations)
    ratio = mh["odds_ratio"]
    print(
        "Rapport de cotes ajuste sur le gang (Mantel-Haenszel) : "
        + (
            f"{ratio:.2f}  IC95 [{mh['ci_low']:.2f}-{mh['ci_high']:.2f}]"
            if ratio is not None
            else "non calculable"
        )
        + f"  ({len(mh['strates_informatives'])} gang(s) informatif(s) sur "
        f"{mh['strates_total']})"
    )
    print("\nDetail par gang (publiee : presse/total | non publiee : presse/total) :")
    for gang, (a, b, c, d) in sorted(mh["detail"].items()):
        marque = "*" if gang in mh["strates_informatives"] else " "
        print(f"  {marque} {gang:<14} {a:3}/{a + b:<4} | {c:3}/{c + d:<4}")
    print(
        "  (* = gang informatif : il porte les deux statuts et au moins un cas de presse)"
    )

    print("\nLECTURE")
    if ratio is not None and mh["ci_low"] <= 1 <= mh["ci_high"]:
        print(
            "  Ajuste sur le gang, l'intervalle du rapport de cotes CONTIENT 1 : "
            "aucun effet\n  du statut n'est etabli, dans un sens comme dans l'autre."
        )
    if p >= 0.05:
        print(
            "  L'ecart n'est PAS statistiquement significatif : on ne peut pas "
            "affirmer que\n  le statut « publiee » predit une confirmation par la presse."
        )
    else:
        print("  L'ecart est statistiquement significatif (p < 0,05).")

    print("\nLIMITES DE L'ETALON (a citer avec tout chiffre)")
    print(
        "  - la presse est une etiquette POSITIVE seulement : son absence ne prouve rien ;"
    )
    print(
        "  - elle arrive AVEC RETARD : une victime recente n'a pas encore ete couverte ;"
    )
    print("  - elle privilegie les GRANDES organisations et les gangs mediatises ;")
    print("  - le statut est observe aujourd'hui, la presse a pu paraitre avant :")
    print("    c'est une ASSOCIATION, pas une prediction au sens temporel ;")
    print(
        "  - « confirmee » n'est pas validee ici : la presse EST son critere (circulaire)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
