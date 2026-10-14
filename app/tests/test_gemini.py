
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from app.core.config import settings

BASE = "https://generativelanguage.googleapis.com/v1beta"


def show(title: str, r: httpx.Response) -> None:
    print(f"\n[{title}] HTTP {r.status_code}")
    print(r.text[:600])


def main() -> None:
    key = settings.GEMINI_API_KEY
    if not key:
        print("❌ GEMINI_API_KEY está vacía.")
        return
    print(f"Clave detectada: {key[:4]}...{key[-4:]} (longitud {len(key)})")
    print(f"Modelo chat: {settings.GEMINI_MODEL} | embeddings: {settings.GEMINI_EMBEDDING_MODEL}")
    headers = {"x-goog-api-key": key.strip()}

    r = httpx.post(
        f"{BASE}/models/{settings.GEMINI_MODEL}:generateContent",
        headers=headers,
        json={"contents": [{"role": "user", "parts": [{"text": "Responde solo: OK"}]}]},
        timeout=30,
    )
    show("generateContent", r)

    r = httpx.post(
        f"{BASE}/models/{settings.GEMINI_EMBEDDING_MODEL}:embedContent",
        headers=headers,
        json={
            "model": f"models/{settings.GEMINI_EMBEDDING_MODEL}",
            "content": {"parts": [{"text": "tubo galvanizado"}]},
            "outputDimensionality": 1536,
        },
        timeout=30,
    )
    print(f"\n[embedContent] HTTP {r.status_code}")
    print(r.text[:200] if r.status_code != 200 else f"OK, dimensiones: {len(r.json()['embedding']['values'])}")


if __name__ == "__main__":
    main()