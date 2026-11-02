"""Rapport mensuel de direction (RSSI) en PDF -- AGREGATS UNIQUEMENT.

⚠️ Aucun nom de victime, aucune valeur, aucune URL de fuite : ce document est
destine a une instance de gouvernance, pas a l'investigation (doctrine du
profil `viewer`, core/roles.py). Marque TLP:AMBER+STRICT en tete et en pied de
CHAQUE page, comme le rapport d'alerte.

⚠️ DETERMINISTE, sans LLM : un rapport de direction doit pouvoir etre
re-emis identique a partir des memes donnees, et ne pas attendre une minute un
modele local. Chaque chiffre est accompagne de sa source, de sa couverture et
de sa date de calcul -- c'est un INSTANTANE date, comme tout rapport emis.

Une section « Limites de lecture » est TOUJOURS imprimee : sans elle, 35
alertes la premiere semaine (un rattrapage historique) se liraient comme un
pic d'activite, et un cache partiel comme une baisse de la menace.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.pipeline.alerting.admiralty import TLP_DEFINITION, TLP_RAPPORT
from app.services.governance_service import governance
from app.pipeline.reporting.charte_pdf import (
    ENCRE,
    ENCRE_DOUCE,
    ENCRE_PALE,
    FOND_CARTE,
    GRAVITES,
    SIGNAL_IMPRIME,
    RapportCharte,
)
from app.pipeline.reporting.charte_pdf import latin1 as _latin1

_MOIS = (
    "janvier février mars avril mai juin juillet août septembre octobre "
    "novembre décembre"
).split()
_LIBELLES_GRAVITE = {
    "critical": "critiques",
    "high": "élevées",
    "medium": "moyennes",
    "low": "faibles",
}


def libelle_mois(mois: str) -> str:
    annee, numero = mois.split("-")
    return f"{_MOIS[int(numero) - 1]} {annee}"


def _heures(valeur: float | None) -> str:
    if valeur is None:
        return "non mesurable (aucune alerte traitée sur la période)"
    return f"{valeur:.0f} h" if valeur >= 1 else f"{valeur * 60:.0f} min"


# Les libellés de `enrich/geo` sont des clés sans accents ; accentués ici
# pour l'affichage seulement.
CONTINENTS_FR = {
    "Amerique du Nord": "Amérique du Nord",
    "Amerique du Sud": "Amérique du Sud",
    "Oceanie": "Océanie",
}


def rapport_direction_pdf(
    db: Session, mois: str, *, now: datetime | None = None
) -> tuple[bytes, str]:
    """PDF du rapport de direction pour `mois` (« AAAA-MM ») et nom de fichier."""
    g = governance(db, month=mois, now=now)
    service, menace = g["service"], g["sector_threat"]
    perimetre = ", ".join(menace["continents"]) or "non défini"

    pdf = RapportCharte(
        type_document="Rapport de direction",
        rappel=f"Rapport mensuel de veille - {libelle_mois(mois)}",
        tlp=TLP_RAPPORT,
    )
    pdf.set_title(_latin1(f"Rapport de direction - {libelle_mois(mois)}"))
    pdf.set_author("Underworld Monitor")
    pdf.add_page()

    # --- Titre -------------------------------------------------------------
    y = pdf.get_y()
    pdf.set_fill_color(*SIGNAL_IMPRIME)
    pdf.rect(pdf.l_margin, y, 1.6, 17, style="F")
    pdf.set_xy(pdf.l_margin + 5, y)
    pdf.set_font("helvetica", "B", 7)
    pdf.set_char_spacing(0.8)
    pdf.set_text_color(*ENCRE_PALE)
    pdf.cell(0, 4, "RAPPORT MENSUEL DE VEILLE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_char_spacing(0)
    pdf.set_x(pdf.l_margin + 5)
    pdf.set_font("helvetica", "B", 19)
    pdf.set_text_color(*ENCRE)
    pdf.cell(
        0, 8.5, _latin1(libelle_mois(mois).capitalize()), new_x="LMARGIN", new_y="NEXT"
    )
    pdf.set_x(pdf.l_margin + 5)
    pdf.set_font("helvetica", "", 8.5)
    pdf.set_text_color(*ENCRE_DOUCE)
    pdf.cell(
        0,
        4.6,
        _latin1(
            f"Calculé le {g['computed_at'][:16].replace('T', ' ')} UTC  -  périmètre : "
            f"{perimetre}  -  agrégats uniquement, aucune donnée de victime"
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(6)

    # --- En bref --------------------------------------------------------------
    total = service["total"]
    par_gravite = service["by_severity"]
    part = menace["critical_sector_share"]
    taux = service["false_positive_rate"]
    pdf.cartes(
        [
            ("Alertes émises", str(total), None),
            ("Critiques", str(par_gravite.get("critical", 0)), GRAVITES["critical"][1]),
            ("Élevées", str(par_gravite.get("high", 0)), GRAVITES["high"][1]),
            ("Moyennes", str(par_gravite.get("medium", 0)), GRAVITES["medium"][1]),
            (
                "Prise en charge",
                _heures(service["median_hours_to_acknowledge"]).split(" (")[0],
                None,
            ),
            (
                "Résolution",
                _heures(service["median_hours_to_resolve"]).split(" (")[0],
                None,
            ),
            (
                "Faux positifs",
                f"{taux * 100:.0f} %" if taux is not None else "non mesurable",
                None,
            ),
            (
                "Secteurs critiques",
                f"{part * 100:.0f} %" if part is not None else "-",
                None,
            ),
        ]
    )

    # --- 01 Activité du service -------------------------------------------------
    pdf.section(1, "Activité du service sur le mois")
    statuts = service["by_status"]
    pdf.paragraphe(
        f"{total} alerte(s) émise(s) ; ouvertes : {statuts.get('open', 0)}, "
        f"acquittées : {statuts.get('acknowledged', 0)}, "
        f"résolues : {statuts.get('resolved', 0)}.",
        taille=9.5,
    )
    if total:
        pdf.barres(
            "Secteurs touchés",
            [
                (i.get("label_fr") or i["label"], i["count"], bool(i.get("critical")))
                for i in service["by_sector"]
            ],
        )
        pdf.barres(
            "Pays (code ISO 3166)",
            [(i["label"], i["count"], False) for i in service["by_country"]],
        )
        pdf.barres(
            "Groupes attaquants",
            [(i["label"], i["count"], False) for i in service["by_gang"]],
        )

    # --- 02 Menace mondiale --------------------------------------------------------
    # Le contexte mondial AVANT le zoom régional : le cyberespace n'a pas de
    # frontière, le périmètre surveillé est mis en avant, jamais isolé.
    monde = g["world_threat"]
    pdf.section(2, "Menace mondiale - 12 derniers mois")
    part_monde = monde["critical_sector_share"]
    part_perimetre = sum(
        c["share"] or 0 for c in monde["by_continent"] if c["highlighted"]
    )
    pdf.encadre(
        f"{monde['total']} victime(s) publiée(s) dans le monde"
        + (
            f", dont {part_monde * 100:.0f} % dans des secteurs critiques NIS2"
            if part_monde is not None
            else ""
        )
        + f". Le périmètre surveillé ({perimetre}) en représente "
        f"{part_perimetre * 100:.0f} %."
    )
    pdf.tableau(
        [("Continent", 0), ("Victimes", 26), ("Part", 22), ("Secteurs NIS2", 32)],
        [
            [
                CONTINENTS_FR.get(c["label"], c["label"])
                + ("  (périmètre surveillé)" if c["highlighted"] else ""),
                str(c["count"]),
                f"{(c['share'] or 0) * 100:.0f} %",
                f"{c['critical_sector_share'] * 100:.0f} %",
            ]
            for c in monde["by_continent"]
        ],
    )
    pdf.ln(2)

    # --- 03 Zoom sur le périmètre surveillé -----------------------------------------
    pdf.section(3, f"Zoom sur le périmètre surveillé - {perimetre}, 12 derniers mois")
    pdf.encadre(
        f"{menace['total']} victime(s) publiée(s) par des groupes de rançongiciel"
        + (
            f", dont {part * 100:.0f} % dans des secteurs critiques NIS2."
            if part is not None
            else "."
        )
    )
    pdf.tableau(
        [("Mois", 0), ("Secteurs critiques", 40), ("Autres", 28), ("Total", 24)],
        [
            [
                libelle_mois(m["month"]),
                str(m["critical_sector"]),
                str(m["other"]),
                str(m["critical_sector"] + m["other"]),
            ]
            for m in menace["monthly"]
        ],
    )
    pdf.ln(3)
    pdf.barres(
        "Secteurs les plus touchés",
        [
            (i.get("label_fr") or i["label"], i["count"], bool(i.get("critical")))
            for i in menace["by_sector"]
        ],
    )
    pdf.barres(
        "Pays (code ISO 3166)",
        [(i["label"], i["count"], False) for i in menace["by_country"]],
    )
    pdf.barres(
        "Groupes les plus actifs",
        [(i["label"], i["count"], False) for i in menace["by_gang"]],
    )
    pdf.paragraphe(
        f"Source : historiques ransomware.live en cache - {menace['coverage_gangs']} "
        "groupe(s) couvert(s). Pays et secteur DÉCLARÉS par le tiers, non vérifiés.",
        taille=8,
        couleur=ENCRE_PALE,
    )

    # --- 04 Limites ---------------------------------------------------------------
    pdf.section(4, "Limites de lecture")
    for texte in (
        "Le corpus d'alertes est jeune : premières alertes le "
        f"{g['corpus_first_alert_date'] or '-'} ; la première semaine est un "
        "rattrapage historique (sources collectées pour la première fois), pas un pic.",
        "La menace sectorielle ne couvre que les groupes présents dans le cache au "
        "moment du calcul : un nombre plus faible peut refléter une couverture "
        "partielle, pas une baisse de la menace.",
        "Une revendication de rançongiciel est une déclaration de l'attaquant : la "
        "plateforme lit, elle ne télécharge ni ne vérifie le contenu des fuites.",
        "Les délais de traitement ne sont calculables qu'à partir d'alertes "
        "effectivement acquittées ou résolues par un analyste.",
    ):
        pdf.ligne_fait("-", texte, largeur_libelle=5)

    pdf.ln(3)
    pdf.encadre(
        "Document de pilotage : il ne contient aucun nom de victime ni aucune valeur "
        "détectée, seulement des agrégats.",
        accent=ENCRE,
        fond=FOND_CARTE,
        note=f"{TLP_RAPPORT} : {TLP_DEFINITION}",
    )

    return bytes(pdf.output()), f"rapport-direction-{mois}.pdf"
