from datetime import datetime, timezone
import uuid
import pytest

from app.db.models import (
    Claim,
    ClaimEstadoEnum,
    ClaimMessage,
    ClaimTipoBienEnum,
    ClaimTipoEnum,
)
from app.services.telegram_service import format_claim_customer_reply_telegram


def create_sample_claim(db_session, estado=ClaimEstadoEnum.pendiente) -> Claim:
    claim = Claim(
        codigo_seguimiento=f"RC-2026-{uuid.uuid4().hex[:6].upper()}",
        nombre="Lucia Ramirez",
        documento="44556677",
        telefono="987112233",
        correo="lucia.ramirez@example.com",
        direccion="Calle Los Pinos 456, Lima",
        tipo_bien=ClaimTipoBienEnum.producto,
        descripcion_bien='Plancha LAF 1/8" x 1.20 x 2.40 m',
        tipo=ClaimTipoEnum.reclamo,
        detalle="Material oxidado en los bordes",
        pedido_consumidor="Cambio por planchas nuevas sin corrosión",
        estado=estado,
        fecha=datetime.now(timezone.utc),
        fecha_atencion=datetime.now(timezone.utc) if estado == ClaimEstadoEnum.atendido else None,
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)
    return claim


def test_get_tracking_success_and_no_pii(client, db_session):
    claim = create_sample_claim(db_session, estado=ClaimEstadoEnum.pendiente)

    response = client.get(
        f"/api/claims/tracking?codigo={claim.codigo_seguimiento}&documento={claim.documento}"
    )
    assert response.status_code == 200
    data = response.json()

    # Campos requeridos
    assert data["codigo_seguimiento"] == claim.codigo_seguimiento
    assert data["tipo"] == claim.tipo.value
    assert data["estado"] == "pendiente"
    assert data["descripcion_bien"] == claim.descripcion_bien
    assert "fecha" in data
    assert "fecha_limite" in data and data["fecha_limite"] is not None
    assert "dias_habiles_restantes" in data and data["dias_habiles_restantes"] is not None
    assert "mensajes" in data

    # Datos sensibles (PII) NO deben exponerse en tracking público
    for sensitive_field in ("nombre", "documento", "telefono", "correo", "direccion"):
        assert sensitive_field not in data


def test_get_tracking_invalid_credentials_returns_same_404(client, db_session):
    claim = create_sample_claim(db_session)
    expected_detail = "No se encontró ningún reclamo con los datos proporcionados."

    # 1. Documento incorrecto
    resp_bad_doc = client.get(
        f"/api/claims/tracking?codigo={claim.codigo_seguimiento}&documento=99999999"
    )
    assert resp_bad_doc.status_code == 404
    assert resp_bad_doc.json()["detail"] == expected_detail

    # 2. Código inexistente
    resp_bad_code = client.get(
        f"/api/claims/tracking?codigo=RC-2026-NOEXISTE&documento={claim.documento}"
    )
    assert resp_bad_code.status_code == 404
    assert resp_bad_code.json()["detail"] == expected_detail


def test_tracking_excludes_sistema_messages(client, db_session):
    claim = create_sample_claim(db_session)

    m1 = ClaimMessage(claim_id=claim.id, autor="cliente", canal="web", texto="Consulta del cliente")
    m2 = ClaimMessage(claim_id=claim.id, autor="admin", canal="panel", texto="Respuesta del asesor")
    m3 = ClaimMessage(claim_id=claim.id, autor="sistema", canal="sistema", texto="Log interno del sistema")
    db_session.add_all([m1, m2, m3])
    db_session.commit()

    response = client.get(
        f"/api/claims/tracking?codigo={claim.codigo_seguimiento}&documento={claim.documento}"
    )
    assert response.status_code == 200
    mensajes = response.json()["mensajes"]

    assert len(mensajes) == 2
    autores = [m["autor"] for m in mensajes]
    assert "cliente" in autores
    assert "admin" in autores
    assert "sistema" not in autores


def test_post_customer_reply_success_and_triggers_notification(client, db_session, monkeypatch):
    claim = create_sample_claim(db_session, estado=ClaimEstadoEnum.en_proceso)
    calls = []

    def mock_notify(c, texto, conforme):
        calls.append((c.id, texto, conforme))
        return {"status": "mock"}

    monkeypatch.setattr("app.routers.claims.notify_claim_customer_reply", mock_notify)

    payload = {
        "codigo": claim.codigo_seguimiento,
        "documento": claim.documento,
        "texto": "He verificado el pedido y aún falta una pieza.",
        "conforme": None,
    }
    response = client.post("/api/claims/tracking/respuesta", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Verifica que el mensaje se guardó y aparece en la respuesta
    assert any(m["texto"] == payload["texto"] and m["autor"] == "cliente" for m in data["mensajes"])

    # Verifica que se disparó la tarea en background
    assert len(calls) == 1
    assert calls[0][0] == claim.id
    assert calls[0][1] == payload["texto"]
    assert calls[0][2] is None


def test_reopen_atendido_claim_transitions(client, db_session):
    claim = create_sample_claim(db_session, estado=ClaimEstadoEnum.atendido)

    # 1. conforme=False sobre reclamo atendido lo reabre a 'en_proceso' y limpia fecha_atencion
    payload_reabrir = {
        "codigo": claim.codigo_seguimiento,
        "documento": claim.documento,
        "texto": "No estoy de acuerdo con la solución brindada.",
        "conforme": False,
    }
    resp1 = client.post("/api/claims/tracking/respuesta", json=payload_reabrir)
    assert resp1.status_code == 200
    assert resp1.json()["estado"] == "en_proceso"

    db_session.refresh(claim)
    assert claim.estado == ClaimEstadoEnum.en_proceso
    assert claim.fecha_atencion is None

    # Cerrar nuevamente el reclamo
    claim.estado = ClaimEstadoEnum.atendido
    claim.fecha_atencion = datetime.now(timezone.utc)
    db_session.commit()

    # 2. conforme=True sobre reclamo atendido lo deja en 'atendido'
    payload_conforme = {
        "codigo": claim.codigo_seguimiento,
        "documento": claim.documento,
        "texto": "Muchas gracias, ya recibí el material de reemplazo.",
        "conforme": True,
    }
    resp2 = client.post("/api/claims/tracking/respuesta", json=payload_conforme)
    assert resp2.status_code == 200
    assert resp2.json()["estado"] == "atendido"

    db_session.refresh(claim)
    assert claim.estado == ClaimEstadoEnum.atendido
    assert claim.fecha_atencion is not None


def test_rate_limit_10_messages_per_24h(client, db_session):
    claim = create_sample_claim(db_session, estado=ClaimEstadoEnum.en_proceso)

    # Insertar 10 mensajes previos del cliente en las últimas 24 horas
    now = datetime.now(timezone.utc)
    for i in range(10):
        db_session.add(
            ClaimMessage(
                claim_id=claim.id,
                autor="cliente",
                canal="web",
                texto=f"Mensaje previo {i + 1}",
                created_at=now,
            )
        )
    db_session.commit()

    # El mensaje 11 del cliente debe ser rechazado con 429
    payload_11 = {
        "codigo": claim.codigo_seguimiento,
        "documento": claim.documento,
        "texto": "Mensaje número 11 que excede la cuota de spam.",
    }
    response = client.post("/api/claims/tracking/respuesta", json=payload_11)
    assert response.status_code == 429
    assert "límite máximo de 10 mensajes" in response.json()["detail"]


def test_format_claim_customer_reply_telegram_escapes_xss(db_session):
    claim = create_sample_claim(db_session)
    raw_texto = "<b>x</b> intento de inyección de tag"
    telegram_msg = format_claim_customer_reply_telegram(claim, raw_texto, conforme=False)

    # Verifica escape de HTML
    assert "<b>x</b>" not in telegram_msg
    assert "&lt;b&gt;x&lt;/b&gt;" in telegram_msg
    # Verifica presencia de enlace admin y conformidad
    assert "/admin/reclamos" in telegram_msg
    assert "No conforme" in telegram_msg
