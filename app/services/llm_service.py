import time
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

# Códigos HTTP temporales de Gemini: vale la pena reintentar.
_RETRY_STATUS = {429, 500, 503, 504}
_MAX_ATTEMPTS = 3  # intentos por modelo
_BACKOFF_SECONDS = (1, 3)  # espera entre intentos


def _generation_config(model_name: str) -> dict:
    config = {"temperature": 0.2, "maxOutputTokens": 1024}
    # Los modelos "piensan" y esos tokens consumen maxOutputTokens: se reduce el razonamiento.
    if "2.5" in model_name:
        config["thinkingConfig"] = {"thinkingBudget": 0}
    elif "gemini-3" in model_name:
        config["thinkingConfig"] = {"thinkingLevel": "low"}
    return config


def _call_gemini(model_name: str, contents: List[dict]) -> dict:
    """Llama a Gemini con reintentos ante errores temporales (503/429/timeouts)."""
    last_error: Exception = RuntimeError("sin intentos")
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = httpx.post(
                f"{GEMINI_BASE_URL}/models/{model_name}:generateContent",
                headers={"x-goog-api-key": settings.GEMINI_API_KEY},
                json={
                    "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT_KENPAKU}]},
                    "contents": contents,
                    "generationConfig": _generation_config(model_name),
                },
                timeout=20,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code not in _RETRY_STATUS:
                raise
            print(
                f"⚠️ Gemini HTTP {e.response.status_code} (modelo={model_name}), "
                f"intento {attempt + 1}/{_MAX_ATTEMPTS}"
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_error = e
            print(
                f"⚠️ Gemini sin respuesta (modelo={model_name}), "
                f"intento {attempt + 1}/{_MAX_ATTEMPTS}: {e}"
            )
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_BACKOFF_SECONDS[attempt])
    raise last_error


def _call_with_fallback(contents: List[dict]) -> dict:
    """Intenta con el modelo principal y, si sigue caído, con el de respaldo."""
    try:
        return _call_gemini(settings.GEMINI_MODEL, contents)
    except Exception as primary_error:
        fallback = settings.GEMINI_FALLBACK_MODEL
        if not fallback or fallback == settings.GEMINI_MODEL:
            raise
        print(
            f"⚠️ Modelo principal falló ({primary_error}); "
            f"probando respaldo {fallback}"
        )
        return _call_gemini(fallback, contents)


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

        data = _call_with_fallback(
            _build_contents(chat_history, user_message_with_context)
        )

        parts = data["candidates"][0]["content"]["parts"]
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
        if isinstance(e, httpx.HTTPStatusError):
            print(
                f"⚠️ Gemini LLM HTTP {e.response.status_code} "
                f"(modelo={settings.GEMINI_MODEL}): {e.response.text[:500]}"
            )
        else:
            print(f"⚠️ Error al llamar al LLM Gemini: {e}")
        error_reply = (
            "Disculpa las molestias, experimentamos una interrupción momentánea. "
            "Te conectamos de inmediato con un asesor de ventas por WhatsApp para atender tu consulta."
        )
        whatsapp_url = build_whatsapp_handoff_url(user_query)
        return error_reply, True, whatsapp_url