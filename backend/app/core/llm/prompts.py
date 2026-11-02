"""Templates de prompt pour l'analyse conversationnelle de contenu extrait."""

from langchain_core.prompts import PromptTemplate

_ANALYSIS_PROMPT_TEMPLATE = """Tu es un assistant d'analyse pour une plateforme de threat intelligence.
On te fournit le contenu brut d'une page collectée (dark web, paste site) et une question
ou une instruction à son sujet.

Réponds uniquement en texte brut, en français, de façon concise.
Base-toi uniquement sur le contenu fourni : n'invente jamais d'information absente.
Si le contenu ne permet pas de répondre, dis-le clairement plutôt que de deviner.

Contenu :
{webpage_content}

Question : {query}
"""

_ANALYSIS_PROMPT = PromptTemplate(
    input_variables=["webpage_content", "query"],
    template=_ANALYSIS_PROMPT_TEMPLATE,
)


_REFINE_QUERY_PROMPT_TEMPLATE = """Tu es un expert en threat intelligence sur le dark web. Reformule la requête
utilisateur ci-dessous en une requête courte optimisée pour des moteurs de recherche onion.

Règles :
- Garde uniquement les mots-clés déjà présents dans la requête d'origine
- N'ajoute AUCUN mot absent de la requête d'origine, en particulier jamais de terme
  générique comme "onion", "search", "dark web", "deep web" : ces mots ne décrivent
  pas ce qui est cherché et ne feraient que bruiter la recherche
- N'utilise aucun opérateur logique (AND, OR...)
- Limite la requête finale à 5 mots maximum
- Réponds uniquement avec la requête reformulée, rien d'autre

Requête : {query}
"""

REFINE_QUERY_PROMPT = PromptTemplate(
    input_variables=["query"], template=_REFINE_QUERY_PROMPT_TEMPLATE
)


_FILTER_RESULTS_PROMPT_TEMPLATE = """Tu es un expert en threat intelligence. Voici une requête de recherche dark web
et une liste de résultats bruts (index, lien, titre) remontés par plusieurs moteurs de recherche onion.

Sélectionne uniquement les résultats dont le TITRE est réellement en rapport avec la requête.

Écarte notamment :
- les liens de navigation ou de catégorie génériques d'un site/annuaire (ex : "Forums",
  "Marketplaces", "Hosting", "About", "Contact", "Home", pages de catégorie)
- tout résultat dont le titre n'a aucun rapport sémantique avec la requête

Le nombre de résultats pertinents peut être inférieur à 20, voire nul — ne complète jamais
la liste avec des résultats non pertinents juste pour en avoir plus.

Règle : réponds uniquement avec une liste d'indices séparés par des virgules, ou le mot AUCUN
si rien n'est pertinent. Rien d'autre.

Requête : {query}
Résultats :
{results}
"""

FILTER_RESULTS_PROMPT = PromptTemplate(
    input_variables=["query", "results"], template=_FILTER_RESULTS_PROMPT_TEMPLATE
)


_FILTER_ORGANIZATION_CANDIDATES_PROMPT_TEMPLATE = """Tu es un expert en threat intelligence. Voici une liste de chaînes de
caractères extraites automatiquement (NER) de documents dark web/forums, censées être des noms d'organisation
(entreprise, administration, institution) potentiellement touchées par une fuite de données.

L'extraction automatique produit beaucoup de bruit : vocabulaire générique de forum, boutons d'interface, acronymes de
champs de données, titres de section, noms de logiciels/outils sans rapport avec une organisation ciblée.

Sélectionne UNIQUEMENT les chaînes qui désignent réellement un nom d'organisation identifiable (entreprise,
administration, institution, marque commerciale) — pas un logiciel, pas un terme technique, pas un mot de vocabulaire
générique de forum, pas un fragment de texte sans sens.

Écarte notamment :
- les termes génériques de forum ou d'interface (ex : "Register", "Reply", "Timestamp", catégories/titres de section)
- les acronymes de champs de données (ex : "SSN", "DOB", "NDA")
- les noms de logiciels/outils génériques sans lien avec une organisation ciblée (ex : "Transmission", "Utorrent")
  sauf si le contexte laisse clairement entendre qu'il s'agit d'une entreprise éditrice visée par une fuite
- tout fragment illisible ou sans sens

Le nombre de candidats pertinents peut être inférieur au total, voire nul — ne complète jamais la liste avec des
candidats non pertinents juste pour en avoir plus.

Règle : réponds uniquement avec une liste d'indices séparés par des virgules, ou le mot AUCUN si rien n'est
pertinent. Rien d'autre.

Candidats :
{candidates}
"""

FILTER_ORGANIZATION_CANDIDATES_PROMPT = PromptTemplate(
    input_variables=["candidates"],
    template=_FILTER_ORGANIZATION_CANDIDATES_PROMPT_TEMPLATE,
)


def get_prompt_for_model(model_name: str) -> PromptTemplate:
    """Retourne le template de prompt pour `model_name` (même template pour tous les
    modèles supportés — OpenAI, Gemini, Ollama)."""
    match model_name:
        case name if name.startswith(("gpt-", "text-", "gemini-", "ollama:")):
            return _ANALYSIS_PROMPT
        case _:
            raise ValueError(f"Unsupported model: {model_name}")
