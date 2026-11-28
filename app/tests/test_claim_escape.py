from datetime import datetime, timezone
from app.db.models import Claim, ClaimEstadoEnum, ClaimTipoBienEnum, ClaimTipoEnum
from app.services.email_service import render_claim_email_html, render_claim_response_email_html
from app.services.telegram_service import (
    format_new_claim_telegram,
    format_claim_customer_reply_telegram,
)


def test_claim_email_and_telegram_escape_xss():
    """Verifica que campos del cliente con HTML y scripts se escapen en el email y Telegram."""
    xss_nombre = "<b>Juan</b>"
    xss_detalle = "precio < 10 & talla > 5 <script>x</script>\nSegunda linea de detalle"
    xss_bien = 'Tubo <aluminio> & "galvanizado"'

    claim = Claim(
        codigo_seguimiento="RC-2026-999999",
        nombre=xss_nombre,
        documento="12345678",
        telefono="987654321",
        correo="juan@ejemplo.com",
        direccion="Calle Falsa 123",
        tipo_bien=ClaimTipoBienEnum.producto,
        descripcion_bien=xss_bien,
        tipo=ClaimTipoEnum.reclamo,
        detalle=xss_detalle,
        pedido_consumidor="Cambio de producto",
        estado=ClaimEstadoEnum.pendiente,
        fecha=datetime(2026, 3, 2, 10, 0, 0, tzinfo=timezone.utc),
        fecha_limite=datetime(2026, 3, 23, 23, 59, 59, tzinfo=timezone.utc),
    )

    # 1. Constancia HTML de registro
    email_html = render_claim_email_html(claim)

    assert "&lt;b&gt;Juan&lt;/b&gt;" in email_html
    assert "&lt;script&gt;x&lt;/script&gt;" in email_html
    assert "<script>" not in email_html
    assert "</script>" not in email_html
    assert "&amp;" in email_html
    assert "<br>" in email_html  # conservó el salto de línea como <br>
    # Formato estructural del HTML se mantiene
    assert "<!DOCTYPE html>" in email_html
    assert "<table" in email_html

    # 2. Telegram de nuevo reclamo
    telegram_msg = format_new_claim_telegram(claim)

    assert "&lt;b&gt;Juan&lt;/b&gt;" in telegram_msg
    assert "&lt;script&gt;x&lt;/script&gt;" in telegram_msg
    assert "<script>" not in telegram_msg
    assert "</script>" not in telegram_msg
    # No hay '<' o '>' sin escapar en los datos de cliente
    assert "precio &lt; 10 &amp; talla &gt; 5" in telegram_msg
    # Conserva sus propias etiquetas de formato HTML de Telegram
    assert "⚖️ <b>¡NUEVO RECLAMO EN LIBRO VIRTUAL!</b>" in telegram_msg
    assert "<code>RC-2026-999999</code>" in telegram_msg
    assert "<i>Plazo legal de atención: 15 días hábiles" in telegram_msg
    assert "<a href=" in telegram_msg


def test_claim_response_email_and_customer_reply_telegram_escape():
    """Verifica que el email de respuesta y el telegram de réplica del cliente también escapen correctamente."""
    claim = Claim(
        codigo_seguimiento="RC-2026-999999",
        nombre="<b>Juan</b>",
        documento="12345678",
        telefono="987654321",
        correo="juan@ejemplo.com",
        direccion="Calle Falsa 123",
        tipo_bien=ClaimTipoBienEnum.producto,
        descripcion_bien="Tubo",
        tipo=ClaimTipoEnum.reclamo,
        detalle="Detalle",
        pedido_consumidor="Cambio",
        estado=ClaimEstadoEnum.en_proceso,
        fecha=datetime(2026, 3, 2, 10, 0, 0, tzinfo=timezone.utc),
        fecha_limite=datetime(2026, 3, 23, 23, 59, 59, tzinfo=timezone.utc),
    )

    admin_texto = "Estimado: <script>alert('xss')</script>\nFavor revisar precios < 100."
    response_email = render_claim_response_email_html(claim, admin_texto)

    assert "&lt;b&gt;Juan&lt;/b&gt;" in response_email
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in response_email or "&lt;script&gt;alert('xss')&lt;/script&gt;" in response_email
    assert "<script>" not in response_email
    assert "<br>" in response_email

    cliente_texto = "No estoy conforme: <script>bad()</script> & saldo < 0."
    telegram_reply = format_claim_customer_reply_telegram(claim, cliente_texto, conforme=False)

    assert "&lt;b&gt;Juan&lt;/b&gt;" in telegram_reply
    assert "&lt;script&gt;bad()&lt;/script&gt;" in telegram_reply
    assert "<script>" not in telegram_reply
    assert "saldo &lt; 0" in telegram_reply
    # Mantiene etiquetas Telegram
    assert "📩 <b>NUEVA RESPUESTA DE CLIENTE EN RECLAMO</b>" in telegram_reply
    assert "❌ No conforme (Reabierto)" in telegram_reply
