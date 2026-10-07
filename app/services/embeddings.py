from typing import List
from openai import OpenAI
from app.core.config import settings

client: OpenAI = None


def get_openai_client() -> OpenAI:
    global client
    if client is None and settings.OPENAI_API_KEY:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return client


def generate_product_embedding_text(
    nombre: str,
    categoria: str,
    acabado: str = "",
    medida: str = "",
    espesor: str = "",
    ficha_tecnica: str = "",
) -> str:
    """
    Concatena la información técnica del producto para la generación del embedding.
    REGLA: NO incluye precio ni stock (cambian con frecuencia).
    """
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


def get_embedding(text: str) -> List[float]:
    """
    Genera un vector embedding de 1536 dimensiones usando text-embedding-3-small.
    En entorno de prueba sin API key, retorna un vector simulado de 1536 dimensiones.
    """
    openai_client = get_openai_client()
    if not openai_client or not settings.OPENAI_API_KEY:
        # Fallback para pruebas unitarias / entorno sin API Key
        import hashlib
        h = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
        # Vector normalizado simulado de 1536 dimensiones
        return [((h + i) % 100) / 1000.0 for i in range(1536)]

    try:
        response = openai_client.embeddings.create(
            input=text, model="text-embedding-3-small"
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"⚠️ Error generando embedding con OpenAI: {e}")
        # Fallback seguro
        return [0.0] * 1536
