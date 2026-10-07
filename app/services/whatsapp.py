from urllib.parse import quote

from app.core.config import settings


def build_whatsapp_order_url(codigo: str, cliente_nombre: str, total_str: str) -> str:
    """Genera la URL prellenada de WhatsApp para coordinar pago y flete de un pedido."""
    msg = (
        f"¡Hola Comercial Kenpaku! He registrado el pedido *{codigo}* "
        f"a nombre de *{cliente_nombre}* por un total de *S/ {total_str}*. "
        f"Deseo coordinar el pago y el flete."
    )
    return f"https://wa.me/{settings.WHATSAPP_NUMBER}?text={quote(msg)}"


def build_whatsapp_handoff_url(query: str = "") -> str:
    """Genera la URL de WhatsApp para derivación con asesor humano (handoff)."""
    if query:
        msg = f"¡Hola Comercial Kenpaku! Quisiera atención de un asesor para la consulta: {query}"
    else:
        msg = "¡Hola Comercial Kenpaku! Quisiera comunicarme con un asesor de ventas."
    return f"https://wa.me/{settings.WHATSAPP_NUMBER}?text={quote(msg)}"
