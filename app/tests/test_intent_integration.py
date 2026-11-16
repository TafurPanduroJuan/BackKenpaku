"""Integración del modelo de intención (APF3) con el chat, la BD y las alertas.

Se prueba con el modelo REAL exportado (app/ml/model) y con Gemini/Telegram simulados.
"""
import uuid

import pytest

from app.core import rate_limit
from app.core.security import create_access_token, get_password_hash
from app.db.models import ChatLog, ChatRolEnum, User, UserRolEnum
from app.services import intent_model, rag_service

RECLAMO = "mi pedido llegó con los tubos doblados, quiero que lo cambien"
COMPRA = "quiero comprar 10 planchas LAF 1.5 mm"
CONSULTA = "a que hora atienden los domingos"


@pytest.fixture(autouse=True)
def entorno_aislado(monkeypatch):
    """Sin límite de chat, LLM simulado que NO deriva por sí mismo y alertas capturadas (sin Telegram real)."""
    monkeypatch.setattr(rate_limit, "chat_rate_limiter", rate_limit.IPRateLimiter(500, 60))
    monkeypatch.setattr(
        rag_service, "generate_llm_reply", lambda *a, **k: ("Respuesta de prueba.", False, None)
    )
    llamadas = {"handoff": [], "compra": []}
    monkeypatch.setattr(
        "app.routers.chat.notify_chat_handoff", lambda *a, **k: llamadas["handoff"].append(a)
    )
    monkeypatch.setattr(
        "app.routers.chat.notify_chat_purchase_intent", lambda *a, **k: llamadas["compra"].append(a)
    )
    return llamadas


def _logs_usuario(db_session, conversation_id):
    return (
        db_session.query(ChatLog)
        .filter(
            ChatLog.id_conversacion == uuid.UUID(conversation_id),
            ChatLog.rol == ChatRolEnum.user,
        )
        .one()
    )


def test_reclamo_fuerza_handoff_registra_prediccion_y_alerta(client, db_session, entorno_aislado):
    r = client.post("/api/chat", json={"message": RECLAMO})
    assert r.status_code == 200
    data = r.json()

    # El LLM simulado NO derivó: lo fuerza el modelo al detectar un reclamo
    assert data["handoff"] is True
    assert data["whatsapp_url"].startswith("https://wa.me/")
    # La intención es un dato interno: no se expone al cliente
    assert "intent" not in data and "intencion_modelo" not in data

    log = _logs_usuario(db_session, data["conversation_id"])
    assert log.intencion_modelo == 2
    assert log.probabilidad_modelo >= 0.5
    # La regla de palabras clave lo confundía con una compra ("pedido"); se conserva como línea base
    assert log.intencion_etiquetada == 3

    # La respuesta del asistente no lleva predicción
    asistente = (
        db_session.query(ChatLog)
        .filter(ChatLog.id_conversacion == uuid.UUID(data["conversation_id"]), ChatLog.rol == ChatRolEnum.assistant)
        .one()
    )
    assert asistente.intencion_modelo is None and asistente.probabilidad_modelo is None

    # Una sola alerta de derivación, con el motivo; ninguna de compra
    assert len(entorno_aislado["handoff"]) == 1 and entorno_aislado["compra"] == []
    _, origen, motivo = entorno_aislado["handoff"][0]
    assert origen.startswith("Conversación ") and "Reclamo" in motivo


def test_compra_firme_envia_alerta_prioritaria_sin_derivar_al_cliente(client, db_session, entorno_aislado):
    data = client.post("/api/chat", json={"message": COMPRA}).json()

    assert data["handoff"] is False  # el cliente sigue con el asesor IA; el aviso es para el dueño
    assert _logs_usuario(db_session, data["conversation_id"]).intencion_modelo == 3
    assert entorno_aislado["handoff"] == []
    assert len(entorno_aislado["compra"]) == 1
    mensaje, origen, probabilidad = entorno_aislado["compra"][0]
    assert mensaje == COMPRA and origen.startswith("Conversación ") and probabilidad >= 0.5


def test_consulta_general_se_registra_pero_no_dispara_alertas(client, db_session, entorno_aislado):
    data = client.post("/api/chat", json={"message": CONSULTA}).json()

    assert data["handoff"] is False
    assert _logs_usuario(db_session, data["conversation_id"]).intencion_modelo == 0
    assert entorno_aislado["handoff"] == [] and entorno_aislado["compra"] == []


def test_modelo_apagado_no_cambia_el_flujo_ni_rompe_el_chat(client, db_session, monkeypatch, entorno_aislado):
    monkeypatch.setattr(intent_model.settings, "ML_INTENT_ENABLED", False)

    data = client.post("/api/chat", json={"message": RECLAMO}).json()

    assert data["handoff"] is False  # sin modelo, nadie fuerza la derivación (comportamiento anterior)
    log = _logs_usuario(db_session, data["conversation_id"])
    assert log.intencion_modelo is None and log.probabilidad_modelo is None
    assert entorno_aislado["handoff"] == [] and entorno_aislado["compra"] == []

    # El endpoint del APF3 sigue respondiendo con la regla de respaldo
    r = client.post("/api/ml/intent", json={"mensaje_texto": RECLAMO})
    assert r.status_code == 200
    assert r.json()["baja_confianza"] is True and r.json()["probabilidad"] == 0.0


def test_si_falla_la_carga_del_modelo_el_chat_responde(client, db_session, monkeypatch):
    def falla():
        raise RuntimeError("joblib corrupto")

    monkeypatch.setattr(intent_model, "_modelo", falla)

    r = client.post("/api/chat", json={"message": RECLAMO})

    assert r.status_code == 200
    assert _logs_usuario(db_session, r.json()["conversation_id"]).intencion_modelo is None


def test_el_modelo_predice_sobre_texto_anonimizado(monkeypatch):
    vistos = {}

    def espia(registro):
        vistos.update(registro)

    monkeypatch.setattr(rag_service, "predecir_intencion_o_none", espia)
    rag_service.predict_message_intent("mi DNI es 12345678 y quiero comprar tubos")

    assert "12345678" not in vistos["mensaje_texto"] and "[DNI]" in vistos["mensaje_texto"]
    assert vistos["longitud_mensaje"] == len(vistos["mensaje_texto"])
    assert vistos["contiene_palabra_clave_producto"] is True
    assert vistos["timestamp"].endswith("+00:00")  # ISO en UTC, como espera el modelo


def test_endpoint_ml_tiene_rate_limit(client, monkeypatch):
    monkeypatch.setattr(rate_limit, "ml_rate_limiter", rate_limit.IPRateLimiter(2, 60))
    for _ in range(2):
        assert client.post("/api/ml/intent", json={"mensaje_texto": CONSULTA}).status_code == 200
    assert client.post("/api/ml/intent", json={"mensaje_texto": CONSULTA}).status_code == 429


def test_admin_chat_logs_expone_la_prediccion(client, db_session):
    admin = User(
        email="admin@kenpaku.pe",
        password_hash=get_password_hash("AdminKenpaku2026!"),
        rol=UserRolEnum.admin,
        activo=True,
    )
    db_session.add(admin)
    db_session.commit()
    conversation_id = client.post("/api/chat", json={"message": RECLAMO}).json()["conversation_id"]

    headers = {"Authorization": f"Bearer {create_access_token(subject=admin.email)}"}
    items = client.get("/api/admin/chat-logs", headers=headers).json()["items"]

    mios = [i for i in items if i["id_conversacion"] == conversation_id]
    usuario = next(i for i in mios if i["rol"] == "user")
    assistant = next(i for i in mios if i["rol"] == "assistant")
    assert usuario["intencion_modelo"] == 2 and usuario["probabilidad_modelo"] >= 0.5
    assert assistant["intencion_modelo"] is None
