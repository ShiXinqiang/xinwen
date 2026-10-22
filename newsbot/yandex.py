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

def call_yandex_gpt(prompt: str, max_tokens: int = 500, temperature: float = 0.5) -> str | None:
    folder_id, headers = _credentials()
    if not folder_id:
        return None
    body = {
        "modelUri": f"gpt://{folder_id}/yandexgpt-lite",
        "completionOptions": {
            "stream": False,
            "temperature": temperature,
            "maxTokens": max_tokens,
        },
        "messages": [{"role": "user", "text": prompt}],
    }
    try:
        response = requests.post(COMPLETION_URL, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        result = response.json()
        if "result" in result and "alternatives" in result["result"]:
            return result["result"]["alternatives"][0]["message"]["text"]
        return None
    except Exception as e:
        print(f"Ошибка YandexGPT: {e}")
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
