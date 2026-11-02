import re

from app.core.llm.models import Models
from app.core.llm.ollama_models import OllamaModelManager
from app.core.llm.prompts import (
    FILTER_ORGANIZATION_CANDIDATES_PROMPT,
    FILTER_RESULTS_PROMPT,
    REFINE_QUERY_PROMPT,
    get_prompt_for_model,
)


async def generate_response(
    model_name: str, content: str, query: str, temperature: float | None = None
) -> str:
    """Envoie `content` (texte extrait par la collecte) + `query` (question ou
    instruction, ex: "résume ce texte") au LLM sélectionné et retourne sa réponse.

    Usage strictement à la demande (bouton "Résumer" / chat manuel dans la
    section Collecte) — jamais dans le chemin critique d'ingestion.

    `temperature` : laissé à None (défaut du modèle) pour le chat libre ; les
    appelants qui attendent une réponse courte et déterministe (classification,
    filtrage) doivent la fixer bas explicitement — voir `generate_batch_response`.
    """
    prompt_template = get_prompt_for_model(model_name)

    if model_name.startswith("ollama:"):
        model = OllamaModelManager.get_model(model_name[len("ollama:") :])
        prompt = prompt_template.format(webpage_content=content, query=query)
        return await model.generate(prompt=prompt, temperature=temperature)

    model_kwargs = {} if temperature is None else {"temperature": temperature}
    model = Models.get_model(model_name, **model_kwargs)
    chain = prompt_template | model
    response = await chain.ainvoke({"webpage_content": content, "query": query})
    return response.content


# Budget total de contenu (tous pages confondues) pour tenir dans la fenêtre de
# contexte des modèles locaux (ex: Llama 3 8B = 8192 tokens, ~4 caractères/token
# en moyenne pour du texte FR/EN mélangé -> on vise large en dessous de la limite
# pour laisser de la place au prompt système + à la réponse). Réparti entre les
# pages du lot plutôt qu'une limite fixe par page : avec peu de pages, chacune
# garde plus de contenu réel (au-delà du menu de navigation en tête de page,
# souvent responsable à lui seul des ~800 premiers caractères d'un forum).
TOTAL_CHARS_BUDGET = 16000
MIN_CHARS_PER_PAGE = 500
MAX_CHARS_PER_PAGE = 3000


async def generate_batch_response(
    model_name: str, pages: list[dict], query: str
) -> str:
    """Comme `generate_response`, mais sur plusieurs pages collectées en une fois
    (voir POST /api/sources/collect-all). Le contenu est structuré par page pour
    que la réponse du modèle soit elle aussi organisée page par page.

    Le prompt force une réponse tranchée par page (voir per_page_query) : les
    modèles locaux, livrés à eux-mêmes sur une instruction vague comme "réponds
    pour chaque page", ont tendance à décrire la page ("il s'agit d'une page de
    recherche...") plutôt que de répondre à la question posée — ce n'est pas
    utilisable pour un tri rapide par un analyste. Température basse (tâche de
    classification, pas de génération créative)."""
    chars_per_page = max(
        MIN_CHARS_PER_PAGE,
        min(MAX_CHARS_PER_PAGE, TOTAL_CHARS_BUDGET // max(len(pages), 1)),
    )
    combined = "\n\n".join(
        f"--- Page : {page['name']} ---\n{page['text'][:chars_per_page]}"
        for page in pages
    )
    per_page_query = (
        f"{query}\n\n"
        "Pour CHAQUE page ci-dessus, réponds sur sa propre ligne, au format strict :\n"
        "**<nom de la page>** — <réponse>\n\n"
        "Règles impératives :\n"
        "- <réponse> doit répondre DIRECTEMENT à la question posée, jamais par une "
        "description de ce qu'est la page ou de son sujet général.\n"
        "- Si la question appelle un jugement oui/non, commence par OUI ou NON, "
        "puis justifie en une courte phrase (max 20 mots) citant un élément concret "
        "du contenu fourni.\n"
        "- Une page d'accueil, un menu de navigation, un écran de vérification "
        "anti-bot/CAPTCHA ou une invite à désactiver JavaScript ne contiennent pas "
        "l'information cherchée : réponds NON, jamais une phrase évasive du type "
        '"la page ne fournit pas de réponse directe".\n'
        "- N'écris jamais que tu ne peux pas répondre. Si le contenu fourni est "
        "réellement insuffisant pour trancher, réponds INCERTAIN suivi de la raison "
        "précise (ex : contenu tronqué, page vide)."
    )
    raw = await generate_response(model_name, combined, per_page_query, temperature=0.1)
    return _condense_verdicts(raw)


_VERDICT_LINE_RE = re.compile(
    r"^\**(?P<name>[^*\n]+?)\**\s*[—:-]+\s*(?P<verdict>OUI|NON|INCERTAIN)\b\s*[:,—-]*\s*(?P<reason>.*)$",
    re.IGNORECASE,
)


def _condense_verdicts(raw: str) -> str:
    """Reduit une reponse `**Page** — OUI/NON/INCERTAIN : raison` par page a une
    liste courte : uniquement les OUI (avec justification), et les INCERTAIN
    regroupes en une ligne pour verification manuelle. Un analyste qui demande
    "lesquelles ont un leak" ne veut pas se retaper la liste complete y compris
    les NON — voir `_parse_result_indices` pour le meme principe applique a la
    recherche (ne jamais compter sur le LLM pour s'auto-limiter, le faire nous-
    memes en post-traitement deterministe).

    Si la reponse ne suit pas le format attendu (query hors classification, ex:
    "resume chaque page"), elle est retournee telle quelle."""
    oui, incertain, non = [], [], []
    for line in raw.splitlines():
        match = _VERDICT_LINE_RE.match(line.strip())
        if not match:
            continue
        name = match.group("name").strip()
        reason = match.group("reason").strip().rstrip(".") or "raison non precisee"
        verdict = match.group("verdict").upper()
        if verdict == "OUI":
            oui.append(f"- **{name}** — {reason}")
        elif verdict == "INCERTAIN":
            incertain.append(name)
        else:
            non.append(name)

    matched_lines = len(oui) + len(incertain) + len(non)
    if matched_lines == 0:
        return raw

    parts = []
    if oui:
        parts.append("**Leaks probables :**\n" + "\n".join(oui))
    else:
        parts.append("Aucune page ne presente de leak avere.")
    if incertain:
        parts.append(
            f"**A verifier manuellement** (contenu insuffisant pour trancher, {len(incertain)}) : "
            + ", ".join(incertain)
        )
    if non:
        parts.append(f"({len(non)} page(s) sans leak detecte, non listee(s))")

    return "\n\n".join(parts)


async def refine_search_query(model_name: str, user_query: str) -> str:
    """Reformule une requête utilisateur en requête courte optimisée pour les
    moteurs de recherche onion (section Recherche, voir pipeline/collect/robin)."""
    if model_name.startswith("ollama:"):
        model = OllamaModelManager.get_model(model_name[len("ollama:") :])
        prompt = REFINE_QUERY_PROMPT.format(query=user_query)
        result = await model.generate(prompt=prompt)
    else:
        model = Models.get_model(model_name)
        chain = REFINE_QUERY_PROMPT | model
        response = await chain.ainvoke({"query": user_query})
        result = response.content
    return result.strip()


def _format_results_for_llm(results: list[dict]) -> str:
    lines = []
    for i, res in enumerate(results, start=1):
        link = re.sub(r"(?<=\.onion).*", "", res["link"])
        title = re.sub(r"[^0-9a-zA-Z\-\.]", " ", res.get("title", ""))
        lines.append(f"{i}. {link} - {title}")
    return "\n".join(lines)


def _parse_result_indices(raw: str, max_index: int) -> list[int]:
    # "AUCUN" est une réponse valide et volontaire (aucun résultat pertinent) : à ne
    # pas confondre avec une réponse du LLM mal formée qu'il faudrait compenser.
    if "aucun" in raw.lower():
        return []

    seen: set[int] = set()
    indices: list[int] = []
    for match in re.findall(r"\d+", raw):
        idx = int(match)
        if 1 <= idx <= max_index and idx not in seen:
            seen.add(idx)
            indices.append(idx)
    if not indices:
        # Réponse du LLM ni "AUCUN" ni exploitable (aucun chiffre) : on garde les 20
        # premiers résultats bruts plutôt que de tout perdre.
        indices = list(range(1, min(max_index, 20) + 1))
    return indices[:20]


async def filter_search_results(
    model_name: str, query: str, results: list[dict]
) -> list[dict]:
    """Sélectionne (via LLM) au plus 20 résultats de recherche pertinents parmi les
    candidats bruts remontés par `search_all_engines`."""
    if not results:
        return []

    formatted = _format_results_for_llm(results)

    if model_name.startswith("ollama:"):
        model = OllamaModelManager.get_model(model_name[len("ollama:") :])
        prompt = FILTER_RESULTS_PROMPT.format(query=query, results=formatted)
        raw = await model.generate(prompt=prompt)
    else:
        model = Models.get_model(model_name)
        chain = FILTER_RESULTS_PROMPT | model
        response = await chain.ainvoke({"query": query, "results": formatted})
        raw = response.content

    indices = _parse_result_indices(raw, len(results))
    return [results[i - 1] for i in indices]


async def filter_organization_candidates(
    model_name: str, names: list[str]
) -> list[str]:
    """Sélectionne (via LLM) les noms, parmi `names` (déjà dédupliqués, sortie
    de DetectionRepository.top_organization_candidates), qui désignent
    réellement des organisations plutôt que du bruit NER (vocabulaire de
    forum, acronymes de champs de données...) — voir
    api/routers/entities.py::list_organization_candidates.

    À la demande uniquement (bouton dédié côté UI, pas dans le backfill
    lui-même) : un appel LLM par page de candidats, jamais par candidat
    individuel, pour rester dans un budget d'appels raisonnable."""
    if not names:
        return []

    formatted = "\n".join(f"{i}. {name}" for i, name in enumerate(names, start=1))

    if model_name.startswith("ollama:"):
        model = OllamaModelManager.get_model(model_name[len("ollama:") :])
        prompt = FILTER_ORGANIZATION_CANDIDATES_PROMPT.format(candidates=formatted)
        raw = await model.generate(prompt=prompt, temperature=0.1)
    else:
        model = Models.get_model(model_name, temperature=0.1)
        chain = FILTER_ORGANIZATION_CANDIDATES_PROMPT | model
        response = await chain.ainvoke({"candidates": formatted})
        raw = response.content

    indices = _parse_result_indices(raw, len(names))
    return [names[i - 1] for i in indices]
