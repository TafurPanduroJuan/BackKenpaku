import logging
from typing import Optional

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
