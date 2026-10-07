from typing import List, Tuple

import httpx

from app.core.config import settings
from app.core.prompts import SYSTEM_PROMPT_KENPAKU
from app.services.embeddings import GEMINI_BASE_URL
from app.services.whatsapp import build_whatsapp_handoff_url


def _build_contents(
    chat_history: List[Tuple[str, str]], user_message: str
) -> List[dict]:
    """Convierte el historial al formato de Gemini (roles 'user' / 'model'), fusionando turnos consecutivos del mismo rol."""
    contents: List[dict] = []
    for rol, msg in list(chat_history[-6:]) + [("user", user_message)]:
        role_name = "user" if rol == "user" else "model"
        if contents and contents[-1]["role"] == role_name:
            contents[-1]["parts"][0]["text"] += "\n" + msg
        else:
            contents.append({"role": role_name, "parts": [{"text": msg}]})
    return contents


def generate_llm_reply(
    user_query: str,
    context_text: str,
    chat_history: List[Tuple[str, str]],  # Lista de (rol, mensaje)
) -> Tuple[str, bool, str]:
    """
    Llama a la API de Gemini pasando el system prompt, contexto de RAG e historial (últimos 6 mensajes).
    Retorna: (reply_text, handoff_boolean, whatsapp_url_or_none)
    """
    if not settings.GEMINI_API_KEY:
        # Modo fallback sin API Key
        reply = (
            f"Basado en nuestro catálogo de Comercial Kenpaku: {context_text}\n\n"
            "¿Deseas coordinar tu pedido o consultar sobre medidas específicas con nuestro equipo?"
        )
        return reply, False, None

    try:
        user_message_with_context = (
            f"CONTEXTO DEL CATÁLOGO KENPAKU:\n{context_text}\n\n"
            f"CONSULTA DEL CLIENTE:\n{user_query}"
        )

        generation_config = {"temperature": 0.2, "maxOutputTokens": 600}
        # Los modelos 2.5 "piensan" y esos tokens consumen maxOutputTokens: se desactiva.
        if "2.5" in settings.GEMINI_MODEL:
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}

        response = httpx.post(
            f"{GEMINI_BASE_URL}/models/{settings.GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": settings.GEMINI_API_KEY},
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT_KENPAKU}]},
                "contents": _build_contents(chat_history, user_message_with_context),
                "generationConfig": generation_config,
            },
            timeout=20,
        )
        response.raise_for_status()

        parts = response.json()["candidates"][0]["content"]["parts"]
        reply_text = "".join(p.get("text", "") for p in parts).strip()
        if not reply_text:
            raise ValueError("Respuesta vacía de Gemini")

        # Detección de handoff (si indica incertidumbre, quejas o cálculos estructurales)
        lower_reply = reply_text.lower()
        handoff_triggers = [
            "consultar a un ingeniero",
            "cálculo estructural",
            "cálculos estructurales",
            "asesor humano",
            "no dispongo de la información",
            "no puedo determinar",
            "reclamo",
            "queja",
        ]

        needs_handoff = any(trigger in lower_reply for trigger in handoff_triggers)
        whatsapp_url = (
            build_whatsapp_handoff_url(user_query) if needs_handoff else None
        )

        return reply_text, needs_handoff, whatsapp_url

    except Exception as e:
        print(f"⚠️ Error al llamar al LLM Gemini: {e}")
        error_reply = (
            "Disculpa las molestias, experimentamos una interrupción momentánea. "
            "Te conectamos de inmediato con un asesor de ventas por WhatsApp para atender tu consulta."
        )
        whatsapp_url = build_whatsapp_handoff_url(user_query)
        return error_reply, True, whatsapp_url