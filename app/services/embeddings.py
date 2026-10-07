import math
from typing import List

import httpx

from app.core.config import settings

EMBEDDING_DIMENSIONS = 1536  # Debe coincidir con la columna Vector(1536) de la BD
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def generate_product_embedding_text(
    nombre: str,
    categoria: str,
    acabado: str = "",
    medida: str = "",
    espesor: str = "",
    ficha_tecnica: str = "",
) -> str:
  
    parts = [
        f"Nombre: {nombre}",
        f"Categoría: {categoria}",
    ]
    if acabado:
        parts.append(f"Acabado: {acabado}")
    if medida:
        parts.append(f"Medida: {medida}")
    if espesor:
        parts.append(f"Espesor: {espesor}")
    if ficha_tecnica:
        parts.append(f"Ficha técnica: {ficha_tecnica}")

    return " | ".join(parts)


def _normalize(vector: List[float]) -> List[float]:
    """Gemini solo entrega vectores normalizados con 3072 dims; con menos hay que normalizar."""
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def get_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> List[float]:
   
    if not settings.GEMINI_API_KEY:
        # Fallback para pruebas unitarias / entorno sin API Key
        import hashlib

        h = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
        return [((h + i) % 100) / 1000.0 for i in range(EMBEDDING_DIMENSIONS)]

    try:
        model = settings.GEMINI_EMBEDDING_MODEL
        response = httpx.post(
            f"{GEMINI_BASE_URL}/models/{model}:embedContent",
            headers={"x-goog-api-key": settings.GEMINI_API_KEY},
            json={
                "model": f"models/{model}",
                "content": {"parts": [{"text": text}]},
                "taskType": task_type,
                "outputDimensionality": EMBEDDING_DIMENSIONS,
            },
            timeout=20,
        )
        response.raise_for_status()
        values = response.json()["embedding"]["values"]
        if len(values) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Dimensiones inesperadas: {len(values)}")
        return _normalize(values)
    except Exception as e:
        print(f"⚠️ Error generando embedding con Gemini: {e}")
        # Fallback seguro
        return [0.0] * EMBEDDING_DIMENSIONS