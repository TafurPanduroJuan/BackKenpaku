from datetime import datetime, timezone
import uuid
import pytest

from app.core.security import create_access_token, get_password_hash
from app.db.models import (
    Claim,
    ClaimEstadoEnum,
    ClaimMessage,
    ClaimTipoBienEnum,
    ClaimTipoEnum,
    User,
    UserRolEnum,
)
from app.services.email_service import render_claim_response_email_html


def create_admin_headers(db_session) -> dict:
    admin = User(
        email=f"admin_{uuid.uuid4().hex[:8]}@kenpaku.pe",
        password_hash=get_password_hash("AdminKenpaku2026!"),
        rol=UserRolEnum.admin,
        activo=True,
    )
    db_session.add(admin)
    db_session.commit()
    token = create_access_token(subject=admin.email)
    return {"Authorization": f"Bearer {token}"}


def create_sample_claim(db_session, estado=ClaimEstadoEnum.pendiente) -> Claim:
    claim = Claim(
        codigo_seguimiento=f"RC-2026-{uuid.uuid4().hex[:6].upper()}",
        nombre="Carlos Santana",
        documento="12345678",
        telefono="987654321",
        correo="carlos@gmail.com",
        direccion="Av. Los Heroes 123",
        tipo_bien=ClaimTipoBienEnum.producto,
        descripcion_bien="Tubo LAC 2x2",
        tipo=ClaimTipoEnum.reclamo,
        detalle="Producto con falla de fábrica evidente",
        pedido_consumidor="Reposición inmediata de la mercadería",
        estado=estado,
        fecha=datetime.now(timezone.utc),
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)
    return claim


def test_reply_to_claim_lifecycle(client, db_session):
    headers = create_admin_headers(db_session)
    claim = create_sample_claim(db_session, estado=ClaimEstadoEnum.pendiente)

    # 1. Responder con estado 'en_proceso'
    payload_en_proceso = {
        "texto": "Estimado cliente, hemos iniciado la revisión técnica de su caso.",
        "estado": "en_proceso",
        "enviar_correo": False,
    }
    resp1 = client.post(
        f"/api/admin/claims/{claim.id}/respuesta",
        json=payload_en_proceso,
        headers=headers,
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["estado"] == "en_proceso"
    assert len(data1["mensajes"]) == 1
    assert data1["mensajes"][0]["autor"] == "admin"
    assert data1["mensajes"][0]["canal"] == "panel"
    assert data1["mensajes"][0]["texto"] == payload_en_proceso["texto"]

    # 2. Responder con estado 'atendido' fija fecha_atencion
    payload_atendido = {
        "texto": "Estimado cliente, se procedió con la reposición del material defectuoso.",
        "estado": "atendido",
        "enviar_correo": False,
    }
    resp2 = client.post(
        f"/api/admin/claims/{claim.id}/respuesta",
        json=payload_atendido,
        headers=headers,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["estado"] == "atendido"
    assert len(data2["mensajes"]) == 2
    db_session.refresh(claim)
    assert claim.fecha_atencion is not None

    # 3. Responder a un reclamo ya atendido devuelve 409
    resp3 = client.post(
        f"/api/admin/claims/{claim.id}/respuesta",
        json={
            "texto": "Intento de respuesta adicional a reclamo cerrado.",
            "estado": "atendido",
            "enviar_correo": False,
        },
        headers=headers,
    )
    assert resp3.status_code == 409
    assert "El reclamo ya fue atendido" in resp3.json()["detail"]


def test_reply_errors_and_auth(client, db_session):
    headers = create_admin_headers(db_session)
    non_existent_id = uuid.uuid4()

    # 1. ID inexistente da 404
    resp_404 = client.post(
        f"/api/admin/claims/{non_existent_id}/respuesta",
        json={
            "texto": "Texto de prueba para verificar 404.",
            "estado": "en_proceso",
        },
        headers=headers,
    )
    assert resp_404.status_code == 404

    # 2. Sin token da 401
    claim = create_sample_claim(db_session)
    resp_401 = client.post(
        f"/api/admin/claims/{claim.id}/respuesta",
        json={
            "texto": "Texto sin credenciales administrativas.",
            "estado": "en_proceso",
        },
    )
    assert resp_401.status_code == 401


def test_patch_claim_status_transitions(client, db_session):
    headers = create_admin_headers(db_session)
    claim = create_sample_claim(db_session, estado=ClaimEstadoEnum.pendiente)

    # 1. Transición pendiente -> atendido es válida y fija fecha_atencion
    patch_resp = client.patch(
        f"/api/admin/claims/{claim.id}/estado",
        json={"estado": "atendido"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["estado"] == "atendido"
    db_session.refresh(claim)
    assert claim.fecha_atencion is not None

    # 2. Transición atendido -> en_proceso es inválida y devuelve 409
    invalid_patch = client.patch(
        f"/api/admin/claims/{claim.id}/estado",
        json={"estado": "en_proceso"},
        headers=headers,
    )
    assert invalid_patch.status_code == 409


def test_get_admin_claims_list_and_detail(client, db_session):
    headers = create_admin_headers(db_session)
    claim = create_sample_claim(db_session, estado=ClaimEstadoEnum.pendiente)

    # Agregar un mensaje al reclamo
    msg = ClaimMessage(
        claim_id=claim.id,
        autor="cliente",
        canal="web",
        texto="Adjunto fotos de respaldo.",
    )
    db_session.add(msg)
    db_session.commit()

    # 1. GET /api/admin/claims
    resp = client.get("/api/admin/claims", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body

    matched = next((item for item in body["items"] if item["id"] == str(claim.id)), None)
    assert matched is not None
    # Campos existentes
    assert matched["codigo_seguimiento"] == claim.codigo_seguimiento
    assert matched["nombre"] == claim.nombre
    assert matched["estado"] == "pendiente"
    # Campos nuevos
    assert "fecha_limite" in matched and matched["fecha_limite"] is not None
    assert "dias_habiles_restantes" in matched and matched["dias_habiles_restantes"] is not None
    assert matched["mensajes_count"] >= 1

    # 2. GET /api/admin/claims/{claim_id}
    detail_resp = client.get(f"/api/admin/claims/{claim.id}", headers=headers)
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["id"] == str(claim.id)
    assert len(detail_data["mensajes"]) >= 1

    # 3. GET /api/admin/claims/{id_inexistente} -> 404
    detail_404 = client.get(f"/api/admin/claims/{uuid.uuid4()}", headers=headers)
    assert detail_404.status_code == 404


def test_render_claim_response_email_html_xss(db_session):
    claim = create_sample_claim(db_session)
    malicious_text = "<script>alert(1)</script>\nSegunda línea de respuesta."
    rendered_html = render_claim_response_email_html(claim, malicious_text)

    # Debe escapar tags HTML peligrosos
    assert "<script>" not in rendered_html
    assert "</script>" not in rendered_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered_html
    # Debe convertir saltos de línea a <br>
    assert "<br>" in rendered_html
    # Debe incluir la frase legal requerida
    assert "Si no está conforme con la respuesta, puede acudir al INDECOPI." in rendered_html


def test_notify_claim_response_called_on_flag(client, db_session, monkeypatch):
    headers = create_admin_headers(db_session)
    claim1 = create_sample_claim(db_session, estado=ClaimEstadoEnum.pendiente)
    claim2 = create_sample_claim(db_session, estado=ClaimEstadoEnum.pendiente)

    calls = []

    def mock_notify(claim, texto):
        calls.append((claim.id, texto))
        return {"status": "mock"}

    monkeypatch.setattr("app.routers.admin.notify_claim_response", mock_notify)

    # 1. enviar_correo = True -> debe llamar a notify_claim_response
    resp1 = client.post(
        f"/api/admin/claims/{claim1.id}/respuesta",
        json={
            "texto": "Respuesta con notificación por correo activada.",
            "estado": "en_proceso",
            "enviar_correo": True,
        },
        headers=headers,
    )
    assert resp1.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] == claim1.id

    # 2. enviar_correo = False -> no debe llamar a notify_claim_response
    calls.clear()
    resp2 = client.post(
        f"/api/admin/claims/{claim2.id}/respuesta",
        json={
            "texto": "Respuesta silenciosa sin envío de correo.",
            "estado": "en_proceso",
            "enviar_correo": False,
        },
        headers=headers,
    )
    assert resp2.status_code == 200
    assert len(calls) == 0
