import logging
from typing import Optional

from app.core.config import settings
from app.db.models import Claim, Order
from app.services.email_service import (
    render_claim_email_html,
    render_order_email_html,
    send_email,
)
from app.services.telegram_service import (
    format_chat_handoff_telegram,
    format_new_claim_telegram,
    format_new_order_telegram,
    format_order_status_telegram,
    send_telegram_alert,
)

logger = logging.getLogger(__name__)


def notify_order_created(order: Order) -> dict:
    """
    Notifica la creación de un nuevo pedido:
    1. Envía correo con token de seguimiento al cliente.
    2. Envía alerta instantánea por Telegram al dueño.
    """
    results = {}
    try:
        # 1. Correo al cliente
        if order.cliente_correo:
            subject = f"¡Pedido Registrado con Éxito! {order.codigo} - Comercial Kenpaku"
            html = render_order_email_html(order, nuevo_estado="pendiente")
            results["email"] = send_email(
                to_email=order.cliente_correo,
                to_name=order.cliente_nombre or "Cliente",
                subject=subject,
                html_content=html,
            )

        # 2. Telegram al dueño
        msg = format_new_order_telegram(order)
        results["telegram"] = send_telegram_alert(msg)
    except Exception as e:
        logger.error(f"[NOTIFICATION ERROR] Error al notificar pedido creado {order.codigo}: {e}")
        results["error"] = str(e)

    return results


def notify_order_status_changed(
    order: Order, nuevo_estado: str, nota: Optional[str] = None
) -> dict:
    """
    Notifica el cambio de estado de un pedido:
    1. Envía correo con el nuevo estado y seguimiento al cliente.
    2. Envía alerta por Telegram al dueño.
    """
    results = {}
    try:
        # 1. Correo al cliente
        if order.cliente_correo:
            estado_title = nuevo_estado.replace("_", " ").title()
            subject = f"Actualización de tu Pedido {order.codigo}: {estado_title}"
            html = render_order_email_html(order, nuevo_estado=nuevo_estado, nota=nota)
            results["email"] = send_email(
                to_email=order.cliente_correo,
                to_name=order.cliente_nombre or "Cliente",
                subject=subject,
                html_content=html,
            )

        # 2. Telegram al dueño
        msg = format_order_status_telegram(order, nuevo_estado=nuevo_estado, nota=nota)
        results["telegram"] = send_telegram_alert(msg)
    except Exception as e:
        logger.error(
            f"[NOTIFICATION ERROR] Error al notificar cambio de estado {order.codigo}: {e}"
        )
        results["error"] = str(e)

    return results


def notify_claim_created(claim: Claim) -> dict:
    """
    Notifica el registro de un nuevo reclamo:
    1. Envía constancia de acuse de recibo legal por correo al cliente.
    2. Envía alerta urgente de reclamo a Telegram al dueño.
    """
    results = {}
    codigo = getattr(claim, "codigo_seguimiento", getattr(claim, "codigo", "RC-XXXXXX"))
    nombre = getattr(claim, "nombre", getattr(claim, "nombre_completo", "Cliente"))

    try:
        # 1. Correo al cliente
        if getattr(claim, "correo", None):
            subject = f"Constancia de Reclamación Virtual {codigo} - Comercial Kenpaku"
            html = render_claim_email_html(claim)
            results["email"] = send_email(
                to_email=claim.correo,
                to_name=nombre,
                subject=subject,
                html_content=html,
            )

        # 2. Telegram al dueño
        msg = format_new_claim_telegram(claim)
        results["telegram"] = send_telegram_alert(msg)
    except Exception as e:
        logger.error(
            f"[NOTIFICATION ERROR] Error al notificar reclamo registrado {codigo}: {e}"
        )
        results["error"] = str(e)

    return results


def notify_chat_handoff(query: str, cliente_info: str = "Cliente web") -> dict:
    """
    Notifica cuando un usuario en el chat de IA solicita atención humana:
    Envía alerta instantánea con la consulta al dueño por Telegram.
    """
    results = {}
    try:
        msg = format_chat_handoff_telegram(query, cliente_info=cliente_info)
        results["telegram"] = send_telegram_alert(msg)
    except Exception as e:
        logger.error(f"[NOTIFICATION ERROR] Error al notificar derivación de chat: {e}")
        results["error"] = str(e)

    return results


def notify_flete_decision(order: Order, decision: str, nota: Optional[str] = None) -> dict:
    """
    Notifica al dueño cuando el cliente acepta o rechaza la cotización del flete a obra.
    """
    results = {}
    caja_url = f"{settings.FRONTEND_URL}/caja/pedidos?codigo={order.codigo}"
    try:
        if decision == "aceptado":
            msg = (
                f"🚚 <b>FLETE ACEPTADO POR EL CLIENTE</b>\n\n"
                f"<b>Pedido:</b> <code>{order.codigo}</code>\n"
                f"<b>Cliente:</b> {order.cliente_nombre} ({order.cliente_telefono})\n"
                f"<b>Costo Flete Aceptado:</b> S/ {order.costo_flete:.2f}\n"
                f"<b>Total a Pagar:</b> S/ {order.total:.2f}\n\n"
                f"👉 <i>El cliente procederá con el pago y la carga de su comprobante.</i>\n\n"
                f"🔗 <a href='{caja_url}'>Ver Pedido en Caja</a>"
            )
        else:
            msg = (
                f"⚠️ <b>FLETE RECHAZADO POR EL CLIENTE</b>\n\n"
                f"<b>Pedido:</b> <code>{order.codigo}</code>\n"
                f"<b>Cliente:</b> {order.cliente_nombre} ({order.cliente_telefono})\n"
                f"<b>Flete Cotizado:</b> S/ {order.costo_flete:.2f}\n"
                f"<b>Motivo:</b> {nota or 'Sin especificar'}\n\n"
                f"👉 <i>Coordinar nuevo flete o cambio a recojo en almacén vía WhatsApp.</i>\n\n"
                f"🔗 <a href='{caja_url}'>Ver Pedido en Caja</a>"
            )
        results["telegram"] = send_telegram_alert(msg)
    except Exception as e:
        logger.error(f"[NOTIFICATION ERROR] Error al notificar decisión de flete {order.codigo}: {e}")
        results["error"] = str(e)

    return results


def notify_voucher_uploaded(order: Order, filename: str) -> dict:
    """
    Notifica al dueño cuando el cliente sube un voucher de pago para su pedido.
    """
    results = {}
    caja_url = f"{settings.FRONTEND_URL}/caja/pedidos?codigo={order.codigo}"
    try:
        msg = (
            f"💳 <b>NUEVO COMPROBANTE DE PAGO SUBIDO</b>\n\n"
            f"<b>Pedido:</b> <code>{order.codigo}</code>\n"
            f"<b>Cliente:</b> {order.cliente_nombre} ({order.cliente_telefono})\n"
            f"<b>Total a Verificar:</b> S/ {order.total:.2f}\n"
            f"<b>Archivo:</b> <code>{filename}</code>\n\n"
            f"👉 <i>Ingresa a caja para validar el comprobante y confirmar la venta.</i>\n\n"
            f"🔗 <a href='{caja_url}'>Validar Comprobante en Caja</a>"
        )
        results["telegram"] = send_telegram_alert(msg)
    except Exception as e:
        logger.error(f"[NOTIFICATION ERROR] Error al notificar voucher subido {order.codigo}: {e}")
        results["error"] = str(e)

    return results

