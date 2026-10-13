import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Order, OrderEstadoEnum, OrderEvent, Product
from app.services.email_service import (
    render_order_email_html,
    render_order_reminder_email_html,
    send_email,
)
from app.services.telegram_service import (
    format_order_auto_expired_telegram,
    send_telegram_alert,
)

logger = logging.getLogger(__name__)


def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normaliza un datetime para que siempre sea offset-aware en UTC (compatible con SQLite y Postgres)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def process_scheduled_tasks(db: Session, simulate_hours: int = 0) -> Dict[str, Any]:
    """
    Ejecuta el lote de automatizaciones programadas (Cron de Fase 5):
    1. Keep-Alive: Ping a la base de datos (evita que Supabase pause el proyecto tras 7 días).
    2. Recordatorios de 24h: Avisa por Brevo a clientes sin respuesta de flete ni voucher subido.
       (Idempotente: se envía solo una vez por pedido; recordatorio_enviado=True).
    3. Expiración y Cancelación de 48h: Anula pedidos vencidos sin confirmación, libera el stock
       reservado, registra OrderEvent con autor='sistema', avisa al cliente por correo y al dueño por Telegram.
    """
    now_utc = datetime.now(timezone.utc)
    effective_now = now_utc + timedelta(hours=simulate_hours)

    results: Dict[str, Any] = {
        "success": True,
        "ejecutado_en": now_utc.isoformat(),
        "simulate_hours": simulate_hours,
        "keepalive_db": False,
        "recordatorios_enviados": 0,
        "pedidos_cancelados_por_vencimiento": 0,
        "stock_liberado_items": 0,
        "pedidos_recordatorio": [],
        "pedidos_cancelados": [],
        "detalles": [],
    }

    # 1. Keep-alive a la base de datos (Postgres / SQLite)
    try:
        db.execute(text("SELECT 1;"))
        results["keepalive_db"] = True
    except Exception as e:
        logger.error(f"[CRON KEEPALIVE ERROR] Error en ping a base de datos: {e}")
        results["keepalive_db"] = False

    reminder_threshold = effective_now - timedelta(hours=settings.CRON_REMINDER_HOURS)
    expiration_threshold = effective_now - timedelta(hours=settings.CRON_EXPIRATION_HOURS)

    # 2. Consultar pedidos pendientes que no tienen comprobante de pago
    candidate_orders = (
        db.query(Order)
        .filter(
            Order.estado.in_([OrderEstadoEnum.pendiente, OrderEstadoEnum.flete_cotizado]),
            Order.voucher_referencia.is_(None),
            Order.fecha_pago.is_(None),
        )
        .all()
    )

    for order in candidate_orders:
        created_at_utc = to_utc(order.created_at)
        if not created_at_utc:
            continue

        # CASO A: Superó las 48 horas -> Cancelar automáticamente y liberar reserva de stock
        if created_at_utc <= expiration_threshold:
            try:
                estado_anterior = order.estado.value
                order.estado = OrderEstadoEnum.cancelado

                # Liberar reserva de stock en inventario
                items_liberados = 0
                if getattr(order, "stock_reservado", False):
                    for item in order.items:
                        product = db.query(Product).filter(Product.id == item.product_id).first()
                        if product and getattr(product, "stock_reservado", 0) > 0:
                            product.stock_reservado = max(0, product.stock_reservado - item.cantidad)
                            items_liberados += item.cantidad
                    order.stock_reservado = False

                # Registrar evento en la línea de tiempo
                nota_cancelacion = (
                    "Cancelación automática por plazo vencido (48 horas sin confirmación ni comprobante de pago). "
                    "Reserva de stock liberada al inventario."
                )
                event = OrderEvent(
                    order_id=order.id,
                    estado_anterior=estado_anterior,
                    estado_nuevo=OrderEstadoEnum.cancelado.value,
                    nota=nota_cancelacion,
                    autor="sistema",
                )
                db.add(event)

                # Enviar correo de aviso de cancelación al cliente
                if order.cliente_correo:
                    subject = f"Aviso de Cancelación de Reserva: Pedido {order.codigo} - Comercial Kenpaku"
                    html = render_order_email_html(
                        order,
                        nuevo_estado="cancelado",
                        nota="Tu pedido ha sido cancelado automáticamente por superar las 48 horas sin validación de pago. Los materiales reservados han sido liberados.",
                    )
                    send_email(
                        to_email=order.cliente_correo,
                        to_name=order.cliente_nombre or "Cliente",
                        subject=subject,
                        html_content=html,
                    )

                # Enviar alerta a Telegram al dueño
                msg_telegram = format_order_auto_expired_telegram(order, motivo=nota_cancelacion)
                send_telegram_alert(msg_telegram)

                results["pedidos_cancelados_por_vencimiento"] += 1
                results["stock_liberado_items"] += items_liberados
                results["pedidos_cancelados"].append(order.codigo)
                results["detalles"].append(
                    f"Pedido {order.codigo} cancelado automáticamente. Se liberaron {items_liberados} und de reserva."
                )
            except Exception as e:
                logger.error(f"[CRON EXPIRATION ERROR] Error cancelando pedido vencido {order.codigo}: {e}")

        # CASO B: Superó las 24 horas y no ha recibido recordatorio -> Enviar recordatorio
        elif created_at_utc <= reminder_threshold and not order.recordatorio_enviado:
            try:
                # Enviar correo de recordatorio vía Brevo
                if order.cliente_correo:
                    subject = f"⏱️ Recordatorio: Tu reserva de materiales en Comercial Kenpaku está por expirar ({order.codigo})"
                    html = render_order_reminder_email_html(order)
                    send_email(
                        to_email=order.cliente_correo,
                        to_name=order.cliente_nombre or "Cliente",
                        subject=subject,
                        html_content=html,
                    )

                # Marcar como enviado (Idempotente)
                order.recordatorio_enviado = True

                # Registrar en la línea de tiempo pública
                event = OrderEvent(
                    order_id=order.id,
                    estado_anterior=order.estado.value,
                    estado_nuevo=order.estado.value,
                    nota="Recordatorio automático de 24 horas enviado al correo del cliente. Reserva de stock por vencer.",
                    autor="sistema",
                )
                db.add(event)

                results["recordatorios_enviados"] += 1
                results["pedidos_recordatorio"].append(order.codigo)
                results["detalles"].append(
                    f"Recordatorio de 24h enviado al pedido {order.codigo}"
                )
            except Exception as e:
                logger.error(f"[CRON REMINDER ERROR] Error procesando recordatorio para {order.codigo}: {e}")

    # Confirmar todos los cambios
    db.commit()

    return results
