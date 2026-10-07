from typing import List, Tuple
from openai import OpenAI

from app.core.config import settings
from app.core.prompts import SYSTEM_PROMPT_KENPAKU
from app.services.whatsapp import build_whatsapp_handoff_url


def generate_llm_reply(
    user_query: str,
    context_text: str,
    chat_history: List[Tuple[str, str]],  # Lista de (rol, mensaje)
) -> Tuple[str, bool, str]:
    """
    Llama a la API de OpenAI (gpt-4o-mini) pasando el system prompt, contexto de RAG e historial (últimos 6 mensajes).
    Retorna: (reply_text, handoff_boolean, whatsapp_url_or_none)
    """
    if not settings.OPENAI_API_KEY:
        # Modo fallback sin API Key
        reply = (
            f"Basado en nuestro catálogo de Comercial Kenpaku: {context_text}\n\n"
            "¿Deseas coordinar tu pedido o consultar sobre medidas específicas con nuestro equipo?"
        )
        return reply, False, None

    try:
        openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

        messages = [{"role": "system", "content": SYSTEM_PROMPT_KENPAKU}]

        # Añadir los últimos 6 mensajes del historial
        for rol, msg in chat_history[-6:]:
            role_name = "user" if rol == "user" else "assistant"
            messages.append({"role": role_name, "content": msg})

        # Añadir consulta del usuario con el contexto de productos recuperado por RAG
        user_message_with_context = (
            f"CONTEXTO DEL CATÁLOGO KENPAKU:\n{context_text}\n\n"
            f"CONSULTA DEL CLIENTE:\n{user_query}"
        )
        messages.append({"role": "user", "content": user_message_with_context})

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
            max_tokens=400,
            timeout=10,
        )

        reply_text = response.choices[0].message.content.strip()

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
        print(f"⚠️ Error al llamar al LLM OpenAI: {e}")
        error_reply = (
            "Disculpa las molestias, experimentamos una interrupción momentánea. "
            "Te conectamos de inmediato con un asesor de ventas por WhatsApp para atender tu consulta."
        )
        whatsapp_url = build_whatsapp_handoff_url(user_query)
        return error_reply, True, whatsapp_url
