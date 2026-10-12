import logging
from typing import Optional
import httpx

from app.core.config import settings
from app.db.models import Claim, Order

logger = logging.getLogger(__name__)


def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    html_content: str,
) -> dict:
    """
    Envía un correo electrónico transaccional usando la API de Brevo.
    Si BREVO_API_KEY no está configurada, opera en modo simulación (mock) sin fallar.
    """
    api_key = settings.BREVO_API_KEY

    # Modo simulación seguro si no hay API key
    if not api_key or not api_key.strip():
        logger.info(
            f"[EMAIL MOCK] Para: {to_email} ({to_name}) | Asunto: '{subject}' | Simulado con éxito."
        )
        return {
            "status": "mock",
            "success": True,
            "to": to_email,
            "subject": subject,
            "message": "Correo simulado con éxito (BREVO_API_KEY no configurada en .env)",
        }

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key": api_key.strip(),
        "Content-Type": "application/json",
        "accept": "application/json",
    }
    payload = {
        "sender": {"name": settings.SENDER_NAME, "email": settings.SENDER_EMAIL},
        "to": [{"email": to_email, "name": to_name}],
        "subject": subject,
        "htmlContent": html_content,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload, headers=headers)
            if response.status_code in (200, 201, 202):
                logger.info(f"[EMAIL ENVIADO] Brevo OK a {to_email}: {response.json()}")
                return {"status": "sent", "success": True, "data": response.json()}
            else:
                logger.warning(
                    f"[EMAIL ERROR] Brevo devolvió {response.status_code}: {response.text}"
                )
                return {
                    "status": "error",
                    "success": False,
                    "code": response.status_code,
                    "detail": response.text,
                }
    except Exception as e:
        logger.error(f"[EMAIL EXCEPTION] Error al conectar con Brevo: {str(e)}")
        return {"status": "exception", "success": False, "detail": str(e)}


def render_order_email_html(
    order: Order,
    nuevo_estado: str = "pendiente",
    nota: Optional[str] = None,
) -> str:
    """Genera una plantilla HTML responsive con identidad visual de Comercial Kenpaku."""
    estado_labels = {
        "pendiente": "Pedido Recibido",
        "flete_cotizado": "Flete de Transporte Cotizado",
        "confirmado": "Pedido Confirmado",
        "listo_para_recojo": "Listo para Recojo en Almacén",
        "despachado": "Despachado en Camino a Obra",
        "entregado": "Pedido Entregado con Éxito",
        "cancelado": "Pedido Cancelado",
    }
    estado_title = estado_labels.get(nuevo_estado, nuevo_estado.replace("_", " ").title())

    mensajes_estado = {
        "pendiente": "Hemos recibido tu solicitud de materiales. Nuestro equipo comercial validará disponibilidad de stock para coordinar contigo.",
        "flete_cotizado": f"Hemos calculado el costo de flete para tu despacho a obra en <strong>S/ {order.costo_flete:.2f}</strong>. El total final es de <strong>S/ {order.total:.2f}</strong>.",
        "confirmado": "Tu pago ha sido validado y los materiales han sido reservados exitosamente en nuestro inventario de almacén.",
        "listo_para_recojo": "Tus materiales ya están empaquetados y separados en nuestro almacén de Puente Piedra (Km 28 Panamericana Norte). Ya puedes pasar a retirarlos con tu DNI.",
        "despachado": "Tus perfiles y planchas van en camino en nuestro camión de reparto. El chofer se comunicará contigo al aproximarse a la obra.",
        "entregado": "Tu pedido ha sido entregado con conformidad. ¡Agradecemos tu preferencia en Comercial Kenpaku S.A.C.!",
        "cancelado": "Te informamos que este pedido ha sido cancelado y el stock correspondiente ha sido liberado.",
    }
    mensaje_cuerpo = mensajes_estado.get(
        nuevo_estado, "El estado de tu pedido ha sido actualizado en nuestro sistema."
    )

    tracking_url = f"{settings.FRONTEND_URL}/seguimiento?token={order.tracking_token or ''}"
    modalidad_str = (
        "Recojo en Almacén Puente Piedra" if order.recojo_en_tienda else "Despacho a Obra"
    )

    items_rows = ""
    for item in order.items:
        nombre = getattr(item, "nombre_snapshot", getattr(item, "nombre", "Producto"))
        subtotal_item = item.cantidad * item.precio_unitario_snapshot
        items_rows += f"""
        <tr>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; font-size: 13px; color: #1e293b;">
                <strong>{nombre}</strong><br>
                <span style="color: #64748b; font-size: 11px;">{item.cantidad} unid. × S/ {item.precio_unitario_snapshot:.2f}</span>
            </td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; font-size: 13px; color: #0f172a; text-align: right; font-weight: bold;">
                S/ {subtotal_item:.2f}
            </td>
        </tr>
        """

    flete_row = ""
    if order.costo_flete and order.costo_flete > 0:
        flete_row = f"""
        <tr>
            <td style="padding: 6px 12px; font-size: 12px; color: #4338ca; font-weight: bold;">Flete de Transporte:</td>
            <td style="padding: 6px 12px; font-size: 12px; color: #4338ca; text-align: right; font-weight: bold;">S/ {order.costo_flete:.2f}</td>
        </tr>
        """

    nota_box = ""
    if nota:
        nota_box = f"""
        <div style="background-color: #f1f5f9; border-left: 4px solid #0284c7; padding: 10px 14px; margin: 16px 0; border-radius: 6px; font-size: 12px; color: #334155;">
            <strong>Nota de actualización:</strong> {nota}
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{estado_title} - {order.codigo}</title>
    </head>
    <body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; padding: 24px 12px;">
            <tr>
                <td align="center">
                    <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="max-width: 600px; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 12px rgba(15,23,42,0.06);">
                        <!-- Header -->
                        <tr>
                            <td style="background-color: #0f172a; padding: 24px 32px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 20px; font-weight: 800; letter-spacing: -0.5px;">
                                    COMERCIAL KENPAKU S.A.C.
                                </h1>
                                <p style="margin: 4px 0 0 0; color: #fbbf24; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">
                                    Aceros y Materiales Siderúrgicos
                                </p>
                            </td>
                        </tr>

                        <!-- Subheader Status -->
                        <tr>
                            <td style="padding: 28px 32px 16px 32px; text-align: center;">
                                <span style="display: inline-block; background-color: #eff6ff; color: #0284c7; border: 1px solid #bfdbfe; font-size: 11px; font-weight: 800; text-transform: uppercase; padding: 4px 12px; border-radius: 9999px;">
                                    {estado_title}
                                </span>
                                <h2 style="margin: 12px 0 6px 0; color: #0f172a; font-size: 22px; font-weight: 800;">
                                    Pedido {order.codigo}
                                </h2>
                                <p style="margin: 0; color: #64748b; font-size: 13px; line-height: 1.5;">
                                    {mensaje_cuerpo}
                                </p>
                                {nota_box}
                            </td>
                        </tr>

                        <!-- Modalidad & Cliente Box -->
                        <tr>
                            <td style="padding: 0 32px 16px 32px;">
                                <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px 18px; font-size: 12px; color: #475569;">
                                    <div style="margin-bottom: 6px;">
                                        <strong style="color: #0f172a;">Cliente:</strong> {order.cliente_nombre}
                                    </div>
                                    <div>
                                        <strong style="color: #0f172a;">Modalidad:</strong> {modalidad_str}
                                    </div>
                                </div>
                            </td>
                        </tr>

                        <!-- Items Table -->
                        <tr>
                            <td style="padding: 0 32px 16px 32px;">
                                <table width="100%" border="0" cellspacing="0" cellpadding="0" style="border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden;">
                                    <tr style="background-color: #f1f5f9;">
                                        <th style="padding: 10px 12px; font-size: 11px; text-align: left; text-transform: uppercase; color: #64748b; font-weight: bold;">Material</th>
                                        <th style="padding: 10px 12px; font-size: 11px; text-align: right; text-transform: uppercase; color: #64748b; font-weight: bold;">Subtotal</th>
                                    </tr>
                                    {items_rows}
                                </table>
                            </td>
                        </tr>

                        <!-- Totals -->
                        <tr>
                            <td style="padding: 0 32px 24px 32px;">
                                <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                    <tr>
                                        <td style="padding: 4px 12px; font-size: 12px; color: #64748b;">Subtotal (sin IGV):</td>
                                        <td style="padding: 4px 12px; font-size: 12px; color: #64748b; text-align: right;">S/ {order.subtotal:.2f}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 4px 12px; font-size: 12px; color: #64748b;">IGV (18%):</td>
                                        <td style="padding: 4px 12px; font-size: 12px; color: #64748b; text-align: right;">S/ {order.igv:.2f}</td>
                                    </tr>
                                    {flete_row}
                                    <tr>
                                        <td style="padding: 10px 12px; font-size: 15px; color: #0f172a; font-weight: 800; border-top: 1px solid #e2e8f0;">Total del Pedido:</td>
                                        <td style="padding: 10px 12px; font-size: 17px; color: #ea580c; text-align: right; font-weight: 800; border-top: 1px solid #e2e8f0;">S/ {order.total:.2f}</td>
                                    </tr>
                                </table>
                            </td>
                        </tr>

                        <!-- Call to Action Button -->
                        <tr>
                            <td style="padding: 0 32px 32px 32px; text-align: center;">
                                <a href="{tracking_url}" target="_blank" style="display: inline-block; background-color: #0f172a; color: #ffffff; text-decoration: none; padding: 14px 28px; border-radius: 12px; font-size: 14px; font-weight: bold; box-shadow: 0 2px 6px rgba(15,23,42,0.15);">
                                    🔍 Ver Seguimiento en Vivo del Pedido
                                </a>
                                <p style="margin: 10px 0 0 0; color: #94a3b8; font-size: 11px;">
                                    Consulta en tiempo real el progreso de tu compra sin necesidad de iniciar sesión.
                                </p>
                            </td>
                        </tr>

                        <!-- Footer -->
                        <tr>
                            <td style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px 32px; text-align: center; color: #94a3b8; font-size: 11px; line-height: 1.5;">
                                <strong style="color: #64748b;">Comercial Kenpaku S.A.C.</strong><br>
                                Almacén Central: Panamericana Norte Km 28, Puente Piedra, Lima - Perú.<br>
                                Atención: Lunes a Sábado de 8:00 am a 6:00 pm.
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def render_claim_email_html(claim: Claim) -> str:
    """Genera la constancia formal de registro en el Libro de Reclamaciones (Normativa Indecopi)."""
    codigo = getattr(claim, "codigo_seguimiento", getattr(claim, "codigo", "RC-2026-000001"))
    nombre = getattr(claim, "nombre", getattr(claim, "nombre_completo", "Estimado cliente"))
    tipo_bien_raw = getattr(claim, "tipo_bien", "Producto")
    tipo_bien_str = tipo_bien_raw.value if hasattr(tipo_bien_raw, "value") else str(tipo_bien_raw)
    detalle = getattr(claim, "detalle", getattr(claim, "detalle_reclamo", ""))

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Constancia de Reclamo {codigo}</title>
    </head>
    <body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="padding: 24px 12px;">
            <tr>
                <td align="center">
                    <table width="100%" max-width="600" border="0" cellspacing="0" cellpadding="0" style="max-width: 600px; background-color: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden;">
                        <tr>
                            <td style="background-color: #0f172a; padding: 20px 32px; text-align: center;">
                                <h1 style="margin: 0; color: #ffffff; font-size: 18px; font-weight: 800;">
                                    LIBRO DE RECLAMACIONES VIRTUAL
                                </h1>
                                <p style="margin: 4px 0 0 0; color: #94a3b8; font-size: 12px;">Comercial Kenpaku S.A.C. | RUC 20601234567</p>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 28px 32px; font-size: 13px; color: #334155; line-height: 1.6;">
                                <p>Estimado(a) <strong>{nombre}</strong>,</p>
                                <p>Le confirmamos la recepción de su registro en nuestro Libro de Reclamaciones con el código oficial:</p>
                                <div style="background-color: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 12px; text-align: center; margin: 16px 0;">
                                    <span style="font-size: 20px; font-weight: 800; color: #0284c7;">{codigo}</span>
                                </div>
                                <p><strong>Tipo de bien:</strong> {tipo_bien_str.title()}<br>
                                <strong>Detalle registrado:</strong> {detalle}</p>
                                <div style="background-color: #f8fafc; border-left: 4px solid #f59e0b; padding: 10px 14px; margin-top: 18px; font-size: 12px; color: #78350f;">
                                    Conforme a la normativa de INDECOPI, daremos respuesta a su requerimiento en un plazo no mayor a quince (15) días hábiles al correo proporcionado.
                                </div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
