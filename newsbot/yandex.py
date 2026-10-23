"""Вызовы YandexGPT: генерация текста и эмбеддинги."""
import requests

from newsbot.config import load_settings

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
EMBEDDING_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"


def _credentials():
    settings = load_settings()
    if not settings.yandex_folder_id or not settings.yandex_api_key:
        print("⚠️ YandexGPT не настроен (YANDEX_FOLDER_ID или YANDEX_API_KEY отсутствуют).")
        return None, None
    return settings.yandex_folder_id, {
        "Authorization": f"Api-Key {settings.yandex_api_key}",
        "Content-Type": "application/json",
    }

class LLMError(Exception):
    pass


def model_uri(folder_id: str, model: str) -> str:
    """«yandexgpt-lite/latest» → gpt://<folder>/yandexgpt-lite/latest; полный URI оставляем как есть."""
    return model if '://' in model else f"gpt://{folder_id}/{model}"

def complete(messages: list[dict], model: str = "yandexgpt-lite/latest",
             max_tokens: int = 500, temperature: float = 0.3) -> tuple[str, int]:
    """
    Запрос к YandexGPT. messages — [{"role": "system"|"user"|"assistant", "text": ...}].
    Возвращает (текст ответа, потрачено токенов). При любой ошибке — LLMError.
    """
    folder_id, headers = _credentials()
    if not folder_id:
        raise LLMError("YandexGPT не настроен")
    body = {
        "modelUri": model_uri(folder_id, model),
        "completionOptions": {"stream": False, "temperature": temperature, "maxTokens": max_tokens},
        "messages": messages,
    }
    try:
        response = requests.post(COMPLETION_URL, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        result = response.json()["result"]
        text = result["alternatives"][0]["message"]["text"]
        tokens = int(result.get("usage", {}).get("totalTokens", 0))
        return text, tokens
    except requests.HTTPError as e:
        raise LLMError(f"YandexGPT ответил {e.response.status_code}: {e.response.text[:200]}") from e
    except Exception as e:
        raise LLMError(f"Ошибка YandexGPT: {e}") from e

def call_yandex_gpt(prompt: str, max_tokens: int = 500, temperature: float = 0.5) -> str | None:
    try:
        return complete([{"role": "user", "text": prompt}], max_tokens=max_tokens, temperature=temperature)[0]
    except LLMError as e:
        print(e)
        return None

def get_embedding(text: str) -> list | None:
    folder_id, headers = _credentials()
    if not folder_id:
        return None
    payload = {
        "modelUri": f"emb://{folder_id}/text-search-query/latest",
        "text": text[:500],
    }
    try:
        response = requests.post(EMBEDDING_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        embedding = response.json().get("embedding")
        if not embedding:
            print("⚠️ В ответе не найден 'embedding'")
        return embedding or None
    except Exception as e:
        print(f"❌ Ошибка получения эмбеддинга: {e}")
        return None
