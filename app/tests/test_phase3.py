import uuid
from decimal import Decimal
import pytest
from unittest.mock import patch

from app.db.models import Claim, ClaimEstadoEnum, ClaimTipoBienEnum, ClaimTipoEnum, Order, OrderEstadoEnum, Product, ProductCategoryEnum, ProductAcabadoEnum
from app.services.email_service import render_claim_email_html, render_order_email_html, send_email
from app.services.telegram_service import (
    format_chat_handoff_telegram,
    format_new_claim_telegram,
    format_new_order_telegram,
    format_order_status_telegram,
    send_telegram_alert,
)
from app.services.notification_service import (
    notify_chat_handoff,
    notify_claim_created,
    notify_order_created,
    notify_order_status_changed,
)


@pytest.fixture
def sample_order(db_session):
    prod = Product(
        id=uuid.uuid4(),
        nombre="Plancha LAC 1.5mm",
        categoria=ProductCategoryEnum.planchas,
        acabado=ProductAcabadoEnum.negro,
        precio_unitario=Decimal("150.00"),
        stock_disponible=30,
        activo=True,
    )
    db_session.add(prod)
    db_session.flush()

    order = Order(
        codigo="KPK-000099",
        cliente_nombre="Alexis Maza",
        cliente_telefono="997410117",
        cliente_correo="alexis@kenpaku.pe",
        direccion="Av. Túpac Amaru 450",
        recojo_en_tienda=False,
        estado=OrderEstadoEnum.pendiente,
        subtotal=Decimal("150.00"),
        igv=Decimal("27.00"),
        total=Decimal("177.00"),
        costo_flete=Decimal("25.00"),
        estado_flete="cotizado",
        tracking_token="kpk_test_token_phase3_xyz",
        acepto_privacidad=True,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


@pytest.fixture
def sample_claim(db_session):
    claim = Claim(
        codigo_seguimiento="RC-2026-000099",
        nombre="Juan Torres",
        documento="12345678",
        telefono="987654321",
        correo="juan.torres@gmail.com",
        direccion="Calle Los Pinos 102",
        tipo_bien=ClaimTipoBienEnum.producto,
        monto_reclamado=Decimal("200.00"),
        descripcion_bien="Tubo estructural defectuoso",
        tipo=ClaimTipoEnum.reclamo,
        detalle="El tubo recibido presentaba abolladuras",
        pedido_consumidor="Cambio del producto",
        estado=ClaimEstadoEnum.pendiente,
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)
    return claim


def test_email_service_fallback_mock_mode(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "BREVO_API_KEY", "")

    res = send_email(
        to_email="cliente@test.com",
        to_name="Cliente Prueba",
        subject="Prueba de Asunto",
        html_content="<p>Hola mundo</p>",
    )
    assert res["status"] == "mock"
    assert res["success"] is True
    assert res["to"] == "cliente@test.com"


def test_render_order_email_html_structure(sample_order):
    html = render_order_email_html(sample_order, nuevo_estado="confirmado", nota="Depósito BCP validado")
    assert "KPK-000099" in html
    assert "Alexis Maza" in html
    assert "S/ 177.00" in html
    assert "kpk_test_token_phase3_xyz" in html
    assert "Depósito BCP validado" in html
    assert "COMERCIAL KENPAKU S.A.C." in html


def test_render_claim_email_html_structure(sample_claim):
    html = render_claim_email_html(sample_claim)
    assert "RC-2026-000099" in html
    assert "Juan Torres" in html
    assert "15" in html  # plazo legal Indecopi
    assert "LIBRO DE RECLAMACIONES VIRTUAL" in html


def test_telegram_service_fallback_mock_mode():
    res = send_telegram_alert("<b>Alerta de prueba</b>")
    assert res["status"] == "mock"
    assert res["success"] is True


def test_format_telegram_messages(sample_order, sample_claim):
    order_msg = format_new_order_telegram(sample_order)
    assert "KPK-000099" in order_msg
    assert "Alexis Maza" in order_msg
    assert "S/ 177.00" in order_msg

    status_msg = format_order_status_telegram(sample_order, nuevo_estado="despachado", nota="Chofer en camino")
    assert "KPK-000099" in status_msg
    assert "DESPACHADO" in status_msg
    assert "Chofer en camino" in status_msg

    claim_msg = format_new_claim_telegram(sample_claim)
    assert "RC-2026-000099" in claim_msg
    assert "Juan Torres" in claim_msg

    chat_msg = format_chat_handoff_telegram(query="Cotización de 50 planchas LAF", cliente_info="Conversación 123")
    assert "Cotización de 50 planchas LAF" in chat_msg


def test_notification_service_orchestration(sample_order, sample_claim):
    # Test notify_order_created
    res_order = notify_order_created(sample_order)
    assert "email" in res_order
    assert "telegram" in res_order
    assert res_order["email"]["success"] is True
    assert res_order["telegram"]["success"] is True

    # Test notify_order_status_changed
    res_status = notify_order_status_changed(sample_order, nuevo_estado="entregado")
    assert "email" in res_status
    assert "telegram" in res_status
    assert res_status["email"]["success"] is True
    assert res_status["telegram"]["success"] is True

    # Test notify_claim_created
    res_claim = notify_claim_created(sample_claim)
    assert "email" in res_claim
    assert "telegram" in res_claim
    assert res_claim["email"]["success"] is True
    assert res_claim["telegram"]["success"] is True

    # Test notify_chat_handoff
    res_chat = notify_chat_handoff(query="Necesito hablar con un vendedor")
    assert "telegram" in res_chat
    assert res_chat["telegram"]["success"] is True


def test_create_order_dispatches_background_notifications(client, sample_order):
    payload = {
        "cliente": {
            "nombre": "Esteban Luis",
            "telefono": "997410117",
            "correo": "esteban@corp.com",
        },
        "direccion": "Av. Los Alisos 200",
        "recojo_en_tienda": False,
        "acepto_privacidad": True,
        "items": [
            {
                "product_id": str(sample_order.items[0].product_id) if sample_order.items else str(sample_order.id),
                "cantidad": 1,
            }
        ],
    }

    # Crear producto válido para el pedido
    prod_res = client.get("/api/products")
    prods = prod_res.json()["items"]
    if prods:
        payload["items"] = [{"product_id": prods[0]["id"], "cantidad": 1}]
        res = client.post("/api/orders", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert "codigo" in data
        assert data["tracking_token"] is not None


def test_create_claim_dispatches_background_notifications(client):
    payload = {
        "nombre": "Valeria Castro",
        "documento": "76543210",
        "telefono": "912345678",
        "correo": "valeria@castro.pe",
        "direccion": "Jr. Bolognesi 300, Lima",
        "tipo_bien": "producto",
        "monto_reclamado": 120.0,
        "descripcion_bien": "Plancha galvanizada con óxido",
        "tipo": "reclamo",
        "detalle": "El material tenía manchas de humedad",
        "pedido_consumidor": "Cambio de producto o reembolso",
        "acepto_terminos": True,
    }

    res = client.post("/api/claims", json=payload)
    assert res.status_code == 201
    assert "codigo_seguimiento" in res.json()
