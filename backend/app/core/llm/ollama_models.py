import aiohttp
import os
import json
import logging

from .errors import LLMErrorMessages

logger = logging.getLogger(__name__)

# A short timeout for control-plane calls (model listing) and a generous one for generation,
# which can stream for minutes on large local models.
_LIST_TIMEOUT = aiohttp.ClientTimeout(total=10)
_GENERATE_TIMEOUT = aiohttp.ClientTimeout(total=600, sock_read=120)


class OllamaModel:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    async def generate(
        self, prompt: str, system_prompt: str = "", temperature: float | None = None
    ) -> str:
        # Les tâches Celery appellent asyncio.run() par tâche : une session singleton
        # se retrouverait liée à une event loop déjà fermée à l'appel suivant.
        # On ouvre donc une session neuve à chaque appel.
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": system_prompt,
            "stream": True,
        }
        if temperature is not None:
            # Température par défaut d'Ollama (~0.8) : trop haute pour une tâche de
            # classification (le modèle divague/décrit la page au lieu de trancher).
            # À baisser explicitement pour les usages qui attendent une réponse
            # courte et déterministe (voir generate_batch_response).
            payload["options"] = {"temperature": temperature}
        try:
            async with aiohttp.ClientSession(timeout=_GENERATE_TIMEOUT) as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    response_parts: list[str] = []
                    async for line in response.content:
                        if line:
                            try:
                                data = json.loads(line.decode("utf-8"))
                                if "response" in data:
                                    response_parts.append(data["response"])
                            except json.JSONDecodeError:
                                logger.warning(f"Error decoding JSON: {line}")

                    return "".join(response_parts)
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Ollama unreachable at {self.base_url}: {e}")
            raise Exception(LLMErrorMessages.OLLAMA_NOT_RUNNING) from e
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                logger.error(f"Model {self.model_name} not found at {self.base_url}")
                raise Exception(LLMErrorMessages.OLLAMA_MODEL_NOT_FOUND) from e
            logger.error(f"Ollama HTTP {e.status}: {e.message}")
            raise Exception(f"Ollama HTTP {e.status}: {e.message}") from e
        except Exception as e:
            # Re-raise the actual error instead of masking it as "Ollama not running"
            logger.exception("Ollama generate failed")
            raise Exception(f"Ollama generate failed: {type(e).__name__}: {e}") from e

    @staticmethod
    async def list_models() -> list[str]:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            async with aiohttp.ClientSession(timeout=_LIST_TIMEOUT) as session:
                async with session.get(f"{base_url}/api/tags") as response:
                    response.raise_for_status()
                    models = await response.json()
                    return [model["name"] for model in models.get("models", [])]
        except aiohttp.ClientConnectorError:
            logger.warning(LLMErrorMessages.OLLAMA_NOT_RUNNING)
            return []
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {str(e)}")
            return []


class OllamaModelManager:
    @staticmethod
    def get_model(model_name: str) -> OllamaModel:
        return OllamaModel(model_name)
