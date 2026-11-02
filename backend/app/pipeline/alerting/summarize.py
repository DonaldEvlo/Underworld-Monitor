"""Resume LLM d'une alerte deja persistee (voir db/models/alert.py), en bout
de pipeline, a la demande -- jamais dans le chemin critique de generation
d'alerte (voir services/alert_service.py, qui ne fait aucun appel LLM).

Reutilise app/core/llm/client.generate_response, deja utilise pour
l'analyse/chat manuel sur du contenu collecte (voir api/routers/llm.py) --
meme mecanisme, nouveau prompt.

Ne recoit jamais de valeur brute : le contenu envoye au LLM est construit a
partir de `value_masked` (deja masque, voir pipeline/detect/masking.py) et de
metadonnees (type, severite, date) -- jamais une valeur qui aurait besoin
d'etre masquee elle-meme. Coherent avec CONTRIBUTING.md §2."""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from app.core.config import settings
from app.core.llm.client import generate_response
from app.db.models.alert import Alert
from app.db.models.entity import Entity
from app.pipeline.reporting.alert_report import (
    _mot_corroboration,
    libelle_credibilite,
)

# Types dont le drapeau `validated` resulte d'une VRAIE validation (Luhn,
# mod-97). Pour un domaine il ne signifie que « format .onion reconnu » : le
# transmettre faisait ecrire au modele « domaines non valides, a verifier en
# priorite » sur des victimes nommees et corroborees (constate le 2026-09-28
# sur Compagnie Aérienne Exemple, alerte critique) -- un doute qui n'existe pas.
_TYPES_A_VALIDATION_REELLE = {"card", "iban"}

# Nombre maximal de valeurs DISTINCTES listees dans le prompt.
#
# Le contenu envoye au LLM n'etait borne par rien : il listait une ligne par
# detection rattachee. Mesure du 2026-09-01 sur la base reelle -- la plus
# grosse alerte (Organisation Exemple) en compte 144, et 4 alertes a 144 concentrent 83 %
# des 692 rattachements existants.
#
# Ces 144 lignes se reduisent a 28 valeurs DISTINCTES : le masquage ramene des
# dizaines d'adresses differentes a la meme chaine (`a***@organisation-exemple.int` y
# figure 14 fois). Regrouper plutot que tronquer borne donc le prompt SANS
# rien perdre -- chaque groupe porte son compte -- et supprime au passage une
# redondance qui degradait le resume : 144 lignes quasi identiques sont
# exactement ce qui pousse un LLM a mal compter, alors que le prompt lui
# interdit d'inventer un chiffre.
#
# 50 laisse de la marge sur le maximum observe (28) tout en garantissant une
# borne. Au-dela, le surplus est ANNONCE dans le contenu plutot que coupe en
# silence : le prompt exige de signaler une information absente, encore
# faut-il que le contenu la signale.
_MAX_DETECTION_GROUPS = 50

_SUMMARY_QUERY = (
    "Rédige, en français UNIQUEMENT (jamais un mot d'anglais, même pour les "
    "termes techniques), un résumé court (3-4 phrases maximum) de cette "
    "alerte de sécurité pour un analyste. Précise le type de détections, le "
    "niveau de gravité global, et ce que l'analyste devrait vérifier en "
    "priorité. Texte brut : aucune mise en forme markdown (ni astérisques, "
    "ni dièses, ni listes).\n\n"
    "Règles impératives :\n"
    "- N'utilise QUE les données listées ci-dessous. Ne cite aucun chiffre "
    "(nombre de détections, pourcentage, quantité) qui n'est pas écrit "
    "textuellement dans les données fournies.\n"
    '- N\'invente jamais un statut, un verdict (ex: "faux positif") ou une '
    "conclusion qui ne figure pas explicitement dans les données.\n"
    "- Si une information demandée est absente des données, dis-le "
    "plutôt que de la deviner.\n"
    "- Le groupe attaquant est l'AUTEUR PRÉSUMÉ de l'attaque : il revendique "
    "la victime, il ne confirme rien. Un agrégateur qui a retrouvé l'annonce "
    "confirme qu'elle existe, pas que la fuite est réelle.\n"
    "- Distingue ce qui est REVENDIQUÉ de ce qui est CONFIRMÉ. Ne recopie "
    "aucune valeur contenant des étoiles."
)


def _build_alert_content(
    alert: Alert,
    subject: str,
    victimes: list[tuple[str, str | None]] | None = None,
) -> str:
    # Regroupement par (type, valeur masquee, validee) -- voir
    # _MAX_DETECTION_GROUPS. La date retenue par groupe est la PLUS ANCIENNE :
    # c'est l'anteriorite reelle du signal, l'information utile a l'analyste.
    groups: Counter[tuple[str, str, bool]] = Counter()
    first_seen: dict[tuple[str, str, bool], date] = {}
    for alert_detection in alert.detections:
        detection = alert_detection.detection
        key = (detection.type, detection.value_masked, detection.validated)
        groups[key] += 1
        detected_on = detection.created_at.date()
        if key not in first_seen or detected_on < first_seen[key]:
            first_seen[key] = detected_on

    # Tri par frequence decroissante, puis par cle : sans ce second critere,
    # deux executions sur les memes donnees pourraient ordonner differemment
    # des groupes a egalite, donc tronquer differemment.
    ordered = sorted(groups.items(), key=lambda item: (-item[1], item[0]))
    shown = ordered[:_MAX_DETECTION_GROUPS]
    omitted = len(ordered) - len(shown)

    lines = [
        f"Périmètre surveillé : {subject}",
        f"Date de l'alerte : {alert.alert_date.isoformat()}",
        f"Sévérité : {alert.severity}",
        f"Nombre de détections rattachées : {len(alert.detections)}",
        f"Nombre de valeurs distinctes : {len(ordered)}",
        *_contexte_de_l_alerte(alert, victimes or []),
        "",
        "Détections (valeurs masquées, regroupées par valeur) :",
    ]
    for key, count in shown:
        type_, value_masked, validated = key
        validation = (
            f", validee={validated}" if type_ in _TYPES_A_VALIDATION_REELLE else ""
        )
        lines.append(
            f"- type={type_}, valeur={value_masked}{validation}, "
            f"occurrences={count}, "
            f"premiere_detection_le={first_seen[key].isoformat()}"
        )
    if omitted:
        lines.append(
            f"- ({omitted} autres valeurs distinctes non listées : la liste est "
            f"bornée aux {_MAX_DETECTION_GROUPS} plus fréquentes)"
        )
    return "\n".join(lines)


def _contexte_de_l_alerte(
    alert: Alert, victimes: list[tuple[str, str | None]]
) -> list[str]:
    """Faits d'enrichissement portes par l'alerte (gang, secteur, credibilite).

    ⚠️ Le prompt datait d'avant tous les enrichissements : le modele ne
    recevait que « type / valeur / validee » et ne pouvait donc ni nommer le
    groupe, ni le secteur, ni la credibilite -- ses resumes se reduisaient a
    « deux domaines non valides ». Memes phrases que le rapport PDF
    (`alert_report`), deja corrigees apres deux erreurs factuelles du modele.
    `getattr` : un champ absent ne doit jamais faire echouer le resume.

    ⚠️ PLUSIEURS VICTIMES (alerte regionale) : gangs, secteur, pays et date
    sont portes par l'ALERTE, pas par chaque victime. Transmis tels quels, le
    modele a ecrit « krybit revendique Suivi Flotte Holdings » -- or Suivi Flotte est
    une victime de DIRE WOLF, krybit revendique Domaine Exemple (constate le
    2026-09-28). Chaque victime est alors listee avec SON gang (lu sur sa
    detection) et les renseignements de niveau alerte ne sont plus attribues."""
    lignes: list[str] = []
    multi = len(victimes) > 1
    if multi:
        lignes.append(
            f"Cette alerte regroupe {len(victimes)} victimes distinctes, chacune "
            "revendiquée par son propre groupe attaquant (auteur présumé, pas un "
            "observateur) -- n'attribue jamais le groupe d'une victime à une autre :"
        )
        for titre, gang in victimes:
            lignes.append(
                f"- {titre} : revendiquée par {gang or 'groupe non attribue'}"
            )
    groupes = [] if multi else getattr(alert, "corroborated_groups", None) or []
    if groupes:
        lignes.append(
            f"Groupe attaquant qui REVENDIQUE la victime : {groupes[0]} "
            "(auteur présumé de l'attaque, pas un observateur)"
        )
        if len(groupes) > 1:
            lignes.append(
                f"Autres groupes revendiquant la même victime : {', '.join(groupes[1:])}"
            )
    statut = getattr(alert, "corroboration_status", None)
    if statut:
        lignes.append(f"Vérification externe : {_mot_corroboration(statut)}")
    credibilite = libelle_credibilite(getattr(alert, "credibility_level", None))
    if credibilite:
        lignes.append(f"Crédibilité de la revendication : {credibilite}")
    if getattr(alert, "press_evidence_url", None):
        portee = " (pour au moins une des victimes)" if multi else ""
        lignes.append(
            "Confirmation extérieure : incident rapporté par la presse ou une "
            f"déclaration officielle{portee}"
        )
    if multi:
        return lignes
    secteur = getattr(alert, "victim_sector", None)
    if secteur:
        lignes.append(f"Secteur d'activité de la victime : {secteur}")
    pays = getattr(alert, "victim_country", None)
    if pays:
        lignes.append(f"Pays de la victime : {pays}")
    date_attaque = getattr(alert, "victim_attack_date", None)
    if date_attaque:
        lignes.append(f"Date d'attaque annoncée : {date_attaque.isoformat()[:10]}")
    return lignes


def alert_subject(alert: Alert, entity: Entity | None) -> str:
    """Ce sur quoi porte l'alerte : le nom de l'entite surveillee, ou le
    perimetre geographique pour une alerte regionale (migration 0016), qui
    n'a par construction aucune entite."""
    if entity is not None:
        return entity.name
    if alert.region:
        return f"Périmètre géographique : {alert.region}"
    return "Périmètre non précisé"


async def summarize_alert(
    alert: Alert,
    subject: str,
    model_name: str,
    victimes: list[tuple[str, str | None]] | None = None,
) -> str:
    """Genere et retourne le resume texte d'une alerte -- ne persiste rien,
    l'appelant (routeur API) decide s'il ecrit le resultat dans
    `alert.summary`. `victimes` : (titre, gang) de chaque victime, voir
    `_contexte_de_l_alerte`."""
    content = _build_alert_content(alert, subject, victimes)
    reperes = _reperes_de_l_alerte(alert, subject, victimes or [])
    for _tentative in range(_TENTATIVES):
        # Temperature nulle : un resume d'alerte rapporte des donnees fournies,
        # il n'en invente pas. Voir SUMMARY_LLM_TEMPERATURE.
        reponse = await generate_response(
            model_name,
            content,
            _SUMMARY_QUERY,
            temperature=settings.SUMMARY_LLM_TEMPERATURE,
        )
        resume = _sans_markdown(reponse)
        if _parle_de_l_alerte(resume, reperes):
            return resume
    raise ValueError("Le modèle a rendu un texte sans rapport avec l'alerte")


# ⚠️ Reponse HORS SUJET, constatee le 2026-09-28 : pour l'alerte cgcgabon,
# la passe de pre-generation a rendu DEUX FOIS « Il semble que votre message
# ait ete interrompu... Je suis la pour vous aider » -- alors que le MEME
# prompt, envoye seul, donnait un resume correct (deux fois). Malgre la
# temperature nulle, l'echec depend de ce qui a tourne juste avant sur Ollama
# (cause exacte non etablie). Plutot que de parier sur la cause : un resume
# qui ne cite RIEN de l'alerte est rejete et redemande ; au second echec
# l'alerte reste sans resume -- « pas encore resumee » vaut mieux qu'un texte
# absurde sous une alerte.
_TENTATIVES = 2


def _reperes_de_l_alerte(
    alert: Alert, subject: str, victimes: list[tuple[str, str | None]]
) -> set[str]:
    """Mots qu'un vrai resume de CETTE alerte cite forcement : sujet, gangs,
    victimes, valeurs detectees (sans leurs parties masquees)."""
    textes = [subject]
    textes += getattr(alert, "corroborated_groups", None) or []
    for titre, gang in victimes:
        textes += [titre, gang or ""]
    for alert_detection in alert.detections:
        textes.append(alert_detection.detection.value_masked)
    reperes: set[str] = set()
    for texte in textes:
        for mot in re.findall(r"[\w.-]+", texte.lower()):
            mot = mot.strip(".-")
            if len(mot) >= 4 and "*" not in mot:
                reperes.add(mot)
    return reperes


def _parle_de_l_alerte(resume: str, reperes: set[str]) -> bool:
    texte = resume.lower()
    return bool(resume.strip()) and (
        not reperes or any(repere in texte for repere in reperes)
    )


def _sans_markdown(texte: str) -> str:
    """La consigne interdit le markdown mais qwen3 met encore du gras : les
    asterisques s'affichent tels quels dans l'interface."""
    texte = texte.replace("**", "").replace("__", "")
    return re.sub(r"(?m)^\s*#+\s*", "", texte).strip()
