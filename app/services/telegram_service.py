import html
import logging
from typing import Optional
import httpx

from app.core.config import settings
from app.db.models import Claim, Order
from app.services.business_days import claim_fecha_limite, dias_habiles_restantes

logger = logging.getLogger(__name__)


def send_telegram_alert(text: str) -> dict:
    """
    Envía un mensaje de alerta al bot de Telegram del administrador/dueño.
    Si TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no están configurados, opera en modo simulación (mock).
    """
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID

    if not token or not token.strip() or not chat_id or not chat_id.strip():
        logger.info(
            f"[TELEGRAM MOCK] Alerta simulada al dueño:\n{text}"
        )
        return {
            "status": "mock",
            "success": True,
            "message": "Alerta de Telegram simulada con éxito (variables no configuradas en .env)",
        }

    url = f"https://api.telegram.org/bot{token.strip()}/sendMessage"
    payload = {
        "chat_id": chat_id.strip(),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(url, json=payload)
            if response.status_code == 200:
                logger.info("[TELEGRAM ENVIADO] Alerta recibida por Telegram con éxito.")
                return {"status": "sent", "success": True, "data": response.json()}
            else:
                logger.warning(
                    f"[TELEGRAM ERROR] Telegram API devolvió {response.status_code}: {response.text}"
                )
                return {
                    "status": "error",
                    "success": False,
                    "code": response.status_code,
                    "detail": response.text,
                }
    except Exception as e:
        logger.error(f"[TELEGRAM EXCEPTION] Error al conectar con Telegram: {str(e)}")
        return {"status": "exception", "success": False, "detail": str(e)}


def format_new_order_telegram(order: Order) -> str:
    """Formatea la alerta de nuevo pedido recibido (venta virtual) para Telegram."""
    modalidad = (
        "🏬 Recojo en Almacén Puente Piedra"
        if order.recojo_en_tienda
        else "🚚 Despacho a Obra"
    )
    caja_url = f"{settings.FRONTEND_URL}/caja/pedidos?codigo={order.codigo}"

    dni_match = None
    if getattr(order, "observaciones", None):
        import re
        m = re.search(r"\[DNI:\s*([0-9]{8})\]", order.observaciones)
        if m:
            dni_match = m.group(1)

    dni_line = f"\n<b>DNI:</b> <code>{dni_match}</code>" if dni_match else ""
    correo_line = (
        f"\n<b>Correo:</b> {order.cliente_correo}"
        if getattr(order, "cliente_correo", None)
        else "\n<b>Correo:</b> <i>No registrado</i>"
    )

    direccion_line = ""
    if not order.recojo_en_tienda and getattr(order, "direccion", None):
        direccion_line = f"\n<b>Dirección:</b> {order.direccion}\n⚠️ <i>Requiere cotización de flete por caja.</i>"

    items_block = ""
    if hasattr(order, "items") and order.items:
        items_block = "\n\n<b>📦 Ítems solicitados:</b>\n"
        for item in order.items:
            nombre = getattr(item, "nombre_snapshot", getattr(item, "nombre", "Producto"))
            items_block += f"• {item.cantidad}x {nombre} — S/ {item.precio_unitario_snapshot:.2f}\n"

    return (
        f"🛒 <b>¡NUEVA VENTA VIRTUAL REGISTRADA!</b>\n\n"
        f"<b>Código:</b> <code>{order.codigo}</code>\n"
        f"<b>Cliente:</b> {order.cliente_nombre}"
        f"{dni_line}"
        f"{correo_line}\n"
        f"<b>Teléfono:</b> {order.cliente_telefono}\n"
        f"<b>Modalidad:</b> {modalidad}"
        f"{direccion_line}"
        f"{items_block}\n"
        f"<b>Total:</b> <b>S/ {order.total:.2f}</b>\n\n"
        f"👉 <a href='{caja_url}'>Atender en Panel de Caja</a>"
    )


def format_order_status_telegram(
    order: Order, nuevo_estado: str, nota: Optional[str] = None
) -> str:
    """Formatea la alerta de cambio de estado de un pedido para Telegram."""
    estado_str = nuevo_estado.replace("_", " ").upper()
    caja_url = f"{settings.FRONTEND_URL}/caja/pedidos?codigo={order.codigo}"
    nota_str = f"\n<b>Nota:</b> {nota}" if nota else ""
    correo_str = (
        f"\n<b>Correo:</b> {order.cliente_correo}"
        if getattr(order, "cliente_correo", None)
        else ""
    )

    return (
        f"📦 <b>VENTA VIRTUAL {order.codigo} - ESTADO ACTUALIZADO</b>\n\n"
        f"<b>Nuevo Estado:</b> <b>{estado_str}</b>\n"
        f"<b>Cliente:</b> {order.cliente_nombre}"
        f"{correo_str}\n"
        f"<b>Teléfono:</b> {order.cliente_telefono}\n"
        f"<b>Total:</b> S/ {order.total:.2f}"
        f"{nota_str}\n\n"
        f"👉 <a href='{caja_url}'>Ver en Panel de Caja</a>"
    )


def format_new_claim_telegram(claim: Claim) -> str:
    """Formatea la alerta de nuevo reclamo en el Libro de Reclamaciones para Telegram."""
    admin_url = f"{settings.FRONTEND_URL}/admin/reclamos"
    codigo = getattr(claim, "codigo_seguimiento", getattr(claim, "codigo", "RC-2026-000001"))
    nombre = getattr(claim, "nombre", getattr(claim, "nombre_completo", "Cliente"))
    telefono = getattr(claim, "telefono", "Sin teléfono")
    tipo_bien_raw = getattr(claim, "tipo_bien", "Producto")
    tipo_bien_str = tipo_bien_raw.value if hasattr(tipo_bien_raw, "value") else str(tipo_bien_raw)
    detalle = getattr(claim, "detalle", getattr(claim, "detalle_reclamo", ""))

    fl = claim_fecha_limite(claim)
    fecha_limite_str = fl.strftime("%d/%m/%Y")

    return (
        f"⚖️ <b>¡NUEVO RECLAMO EN LIBRO VIRTUAL!</b>\n\n"
        f"<b>Código:</b> <code>{codigo}</code>\n"
        f"<b>Cliente:</b> {nombre}\n"
        f"<b>Teléfono:</b> {telefono}\n"
        f"<b>Tipo:</b> {tipo_bien_str.title()}\n"
        f"<b>Detalle:</b> {detalle[:120]}...\n\n"
        f"⚠️ <i>Plazo legal de atención: 15 días hábiles (hasta {fecha_limite_str}).</i>\n\n"
        f"👉 <a href='{admin_url}'>Gestionar Reclamo</a>"
    )


def format_claim_customer_reply_telegram(
    claim: Claim, texto: str, conforme: Optional[bool] = None
) -> str:
    """Formatea la alerta de nueva respuesta del cliente a un reclamo para Telegram."""
    admin_url = f"{settings.FRONTEND_URL}/admin/reclamos"
    codigo = getattr(claim, "codigo_seguimiento", getattr(claim, "codigo", "RC-XXXXXX"))
    nombre = getattr(claim, "nombre", getattr(claim, "nombre_completo", "Cliente"))

    if conforme is True:
        conforme_line = "\n<b>Conformidad:</b> ✅ Conforme"
    elif conforme is False:
        conforme_line = "\n<b>Conformidad:</b> ❌ No conforme (Reabierto)"
    else:
        conforme_line = "\n<b>Conformidad:</b> ℹ️ No especificado"

    fl = claim_fecha_limite(claim)
    estado_val = claim.estado.value if hasattr(claim.estado, "value") else str(claim.estado)
    if estado_val == "atendido":
        plazo_line = "Atendido"
    else:
        dias = dias_habiles_restantes(fl)
        if dias < 0:
            plazo_line = f"⚠️ Vencido ({abs(dias)} días hábiles de retraso)"
        elif dias == 0:
            plazo_line = "⚠️ Vence hoy"
        else:
            plazo_line = f"{dias} días hábiles restantes"

    texto_trunc = texto[:300]
    texto_escaped = html.escape(texto_trunc)

    return (
        f"📩 <b>NUEVA RESPUESTA DE CLIENTE EN RECLAMO</b>\n\n"
        f"<b>Código:</b> <code>{codigo}</code>\n"
        f"<b>Cliente:</b> {nombre}"
        f"{conforme_line}\n"
        f"<b>Plazo legal:</b> {plazo_line}\n\n"
        f"<b>Mensaje del cliente:</b>\n<i>\"{texto_escaped}\"</i>\n\n"
        f"👉 <a href='{admin_url}'>Gestionar Reclamo</a>"
    )


def format_chat_handoff_telegram(
    query: str, cliente_info: str = "Cliente web", motivo: Optional[str] = None
) -> str:
    """Formatea la alerta cuando un cliente solicita un asesor humano en el Chat IA.

    `motivo` (opcional) indica por qué se derivó, p. ej. un reclamo detectado por el modelo de ML.
    """
    motivo_linea = f"<b>Motivo:</b> {motivo}\n" if motivo else ""
    return (
        f"💬 <b>CLIENTE SOLICITA ASESOR HUMANO (CHAT IA)</b>\n\n"
        f"<b>Consulta del cliente:</b>\n<i>\"{query}\"</i>\n\n"
        f"{motivo_linea}"
        f"<b>Origen:</b> {cliente_info}\n"
        f"<b>WhatsApp de atención:</b> +{settings.WHATSAPP_NUMBER}"
    )


def format_chat_purchase_intent_telegram(
    query: str, cliente_info: str = "Cliente web", probabilidad: Optional[float] = None
) -> str:
    """Alerta prioritaria: el modelo de ML detectó intención firme de compra en el Chat IA."""
    prob = f" ({probabilidad:.0%} de confianza)" if probabilidad is not None else ""
    return (
        f"🛒 <b>INTENCIÓN DE COMPRA DETECTADA (CHAT IA)</b>{prob}\n\n"
        f"<b>Mensaje del cliente:</b>\n<i>\"{html.escape(query)}\"</i>\n\n"
        f"<b>Origen:</b> {cliente_info}\n"
        f"<b>Acción sugerida:</b> contactar al cliente cuanto antes para cerrar la venta.\n"
        f"<b>WhatsApp de atención:</b> +{settings.WHATSAPP_NUMBER}"
    )


def format_order_auto_expired_telegram(order: Order, motivo: Optional[str] = None) -> str:
    """Formatea la alerta de cancelación automática por vencimiento de plazo (48h) para Telegram."""
    admin_url = f"{settings.FRONTEND_URL}/admin/pedidos"
    motivo_str = motivo or "Plazo de 48h vencido sin confirmación ni comprobante de pago."
    return (
        f"⏳ <b>PEDIDO CANCELADO POR VENCIMIENTO (SISTEMA)</b>\n\n"
        f"<b>Código:</b> <code>{order.codigo}</code>\n"
        f"<b>Cliente:</b> {order.cliente_nombre} ({order.cliente_telefono})\n"
        f"<b>Total:</b> S/ {order.total:.2f}\n"
        f"<b>Motivo:</b> {motivo_str}\n"
        f"<b>Acción:</b> Reserva de materiales liberada automáticamente al stock.\n\n"
        f"👉 <a href='{admin_url}'>Ver en Panel Admin</a>"
    )

