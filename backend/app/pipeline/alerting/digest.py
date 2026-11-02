"""Synthese LLM de l'ENSEMBLE des alertes ouvertes, en un seul texte.

Complementaire de `summarize.py`, qui resume UNE alerte : ici on repond a
« qu'est-ce qui s'est passe, globalement ? ». C'est la vue qu'un analyste
regarde en arrivant, avant d'ouvrir quoi que ce soit.

Logique pure (voir CONTRIBUTING.md §3.3) : construit le contenu, ne fait aucun appel
reseau ni aucune requete. L'appelant fournit les alertes deja chargees.

Ne recoit jamais de valeur brute : uniquement `value_masked` (deja masque, voir
pipeline/detect/masking.py) et des metadonnees. Coherent avec la regle 2.
"""

from __future__ import annotations

from collections import Counter

from app.db.models.alert import Alert

# Nombre maximal d'alertes DETAILLEES dans le prompt.
#
# Meme raisonnement que `summarize._MAX_DETECTION_GROUPS` : le prompt doit
# etre borne, et le surplus ANNONCE plutot que coupe en silence. Les alertes
# sont triees par severite puis par nombre de detections, si bien qu'une
# troncature ne retire que le moins significatif.
#
# 40 couvre largement l'existant (32 alertes au 2026-09-02) tout en garantissant
# que le prompt ne croisse pas indefiniment avec le corpus.
_MAX_ALERTS_DETAILED = 40

# Valeurs listees par alerte. Une alerte peut en porter beaucoup (144 sur
# l'alerte Organisation Exemple) : les enumerer toutes noierait la synthese, alors que le
# compte total, lui, reste annonce.
_MAX_VALUES_PER_ALERT = 5

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

DIGEST_QUERY = (
    "Rédige, en français UNIQUEMENT (jamais un mot d'anglais, même pour les "
    "termes techniques), une synthèse de 5 à 8 phrases de l'ensemble de ces "
    "alertes de sécurité, destinée à un analyste qui prend son poste.\n\n"
    "Structure attendue :\n"
    "- ce qui ressort en priorité et pourquoi ;\n"
    "- les organisations ou périmètres les plus concernés ;\n"
    "- ce qui est confirmé par une source tierce et ce qui ne l'est pas ;\n"
    "- ce qu'il faut vérifier en premier.\n\n"
    "Règles impératives :\n"
    "- N'utilise QUE les données listées ci-dessous. Ne cite aucun chiffre "
    "qui n'y figure pas textuellement.\n"
    "- Une alerte est CONFIRMÉE par un tiers uniquement si sa ligne le dit "
    "explicitement. Ne déduis jamais ce statut du reste de la ligne.\n"
    "- « Vue par nous seuls » n'est PAS un doute : ne la présente jamais "
    "comme incertaine pour cette raison.\n"
    '- N\'invente aucun statut, verdict ni conclusion ("faux positif", '
    '"résolu") qui ne figure pas dans les données.\n'
    "- Ne produis AUCUN décompte par pays, par région ou par secteur : ces "
    "regroupements ne figurent pas dans les données et seraient inventés. "
    "Essai réel du 2026-09-02 : le modèle a annoncé « 11 alertes en Afrique "
    "du Sud, 5 en Égypte » alors que rien de tel n'y figurait.\n"
    "- Si une information manque, dis-le plutôt que de la deviner."
)


def _subject(alert: Alert, entity_names: dict) -> str:
    if alert.entity_id is not None:
        return entity_names.get(alert.entity_id, str(alert.entity_id))
    if alert.region:
        # Une alerte regionale signale une victime que PERSONNE n'avait
        # declaree : le dire, sinon le LLM la presentera comme une
        # organisation surveillee de plus.
        return f"périmètre {alert.region} (victime non déclarée)"
    return "périmètre non précisé"


def build_digest_content(alerts: list[Alert], entity_names: dict) -> str:
    """Contenu envoye au LLM pour la synthese globale.

    `entity_names` : identifiant d'entite -> nom, fourni par l'appelant (la
    couche pure ne consulte pas la base)."""
    if not alerts:
        return "Aucune alerte ouverte."

    ordered = sorted(
        alerts,
        key=lambda a: (
            _SEVERITY_RANK.get(a.severity, 9),
            -len(a.detections),
            str(a.id),
        ),
    )
    shown = ordered[:_MAX_ALERTS_DETAILED]
    omitted = len(ordered) - len(shown)

    par_severite = Counter(a.severity for a in alerts)
    corroborees = sum(1 for a in alerts if a.corroboration_status == "corroborated")
    regionales = sum(1 for a in alerts if a.scope == "region")

    lines = [
        f"Nombre total d'alertes : {len(alerts)}",
        "Répartition par gravité : "
        + ", ".join(f"{n} {s}" for s, n in par_severite.most_common()),
        f"Alertes CONFIRMÉES par un observateur tiers : {corroborees} "
        f"sur {len(alerts)}",
        f"Alertes de périmètre géographique (victime non déclarée) : {regionales}",
        "",
        "Rappel de lecture : « vue par nous seuls » n'est PAS un doute. Nous "
        "lisons le site de fuite a la source ; un agrégateur tiers ne l'a "
        "simplement pas encore indexée.",
        "",
        "Détail des alertes :",
    ]

    for alert in shown:
        detections = [ad.detection for ad in alert.detections if ad.detection]
        valeurs = sorted({d.value_masked for d in detections if d.value_masked})
        extrait = ", ".join(valeurs[:_MAX_VALUES_PER_ALERT])
        if len(valeurs) > _MAX_VALUES_PER_ALERT:
            extrait += f" (et {len(valeurs) - _MAX_VALUES_PER_ALERT} autres)"

        # ⚠️ Ne PAS passer le statut technique tel quel. Essai reel du
        # 2026-09-02 avec `confirmation=exclusive` : le modele a rendu « seule
        # Organisation Exemple a ete verifiee par un observateur tiers » -- exactement
        # l'inverse, Organisation Exemple etant `exclusive` et Domaine Exemple la seule
        # corroboree. Le mot « exclusive » se lit spontanement comme
        # « exclusif, donc remarquable ». Une synthese qui se trompe sur ce qui
        # est confirme est pire qu'une absence de synthese.
        if alert.corroboration_status == "corroborated":
            etat = "CONFIRMÉE par un observateur tiers"
            if alert.corroborated_group:
                etat += f" (gang {alert.corroborated_group})"
        elif alert.corroboration_status == "exclusive":
            etat = "vue par nous seuls, aucun tiers ne l'a encore publiée"
        else:
            etat = "jamais confrontée a un tiers"

        lines.append(
            f"- {_subject(alert, entity_names)} | gravite={alert.severity} | "
            f"statut={alert.status} | date={alert.alert_date.isoformat()} | "
            f"{len(detections)} détection(s) | confirmation={etat}"
            + (f" | valeurs : {extrait}" if extrait else "")
        )

    if omitted:
        lines.append(
            f"- ({omitted} alertes de moindre gravité non détaillées ici ; "
            f"elles sont comptées dans le total ci-dessus)"
        )
    return "\n".join(lines)
