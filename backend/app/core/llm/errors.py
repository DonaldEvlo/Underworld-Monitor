import os


class LLMErrorMessages:
    """Messages d'erreur pour la connexion aux modèles LLM (loggées, pas affichées à un humain)."""

    OPENAI_API_KEY_MISSING = "Clé API OpenAI manquante (variable d'env OPENAI_API_KEY)."
    GOOGLE_API_KEY_MISSING = "Clé API Google manquante (variable d'env GOOGLE_API_KEY)."
    OPENAI_API_KEY_INVALID = "Clé API OpenAI invalide ou expirée."
    GOOGLE_API_KEY_INVALID = "Clé API Google invalide ou expirée."

    OLLAMA_NOT_RUNNING = "Ollama inaccessible à l'URL configurée (OLLAMA_BASE_URL)."
    OLLAMA_MODEL_NOT_FOUND = (
        "Modèle Ollama introuvable — le tirer d'abord (`ollama pull <model>`)."
    )

    GENERIC_ERROR = "Erreur inattendue lors de l'appel au modèle LLM."


def check_model_api_key(model_name: str) -> str | None:
    """Vérifie que la clé API requise pour `model_name` est présente. Retourne un message
    d'erreur si elle manque, None sinon."""
    if model_name.startswith(("gpt-", "text-")) and not os.getenv("OPENAI_API_KEY"):
        return LLMErrorMessages.OPENAI_API_KEY_MISSING

    if model_name.startswith("gemini-") and not os.getenv("GOOGLE_API_KEY"):
        return LLMErrorMessages.GOOGLE_API_KEY_MISSING

    return None
