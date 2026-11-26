import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.models import ChatLog, ChatRolEnum
from app.routers.auth import create_access_token
from app.services.chat_retention_service import purge_old_chat_logs


@pytest.fixture(autouse=True)
def cleanup_chat_logs(db_session):
    """Limpia los ChatLogs creados durante el test para aislar cada prueba."""
    yield
    db_session.query(ChatLog).delete()
    db_session.commit()


def _crear_mensaje(
    db_session,
    id_conversacion: uuid.UUID,
    timestamp: datetime,
    rol: ChatRolEnum = ChatRolEnum.user,
    texto: str = "Mensaje de prueba",
):
    msg = ChatLog(
        id=uuid.uuid4(),
        id_conversacion=id_conversacion,
        timestamp=timestamp,
        rol=rol,
        mensaje_texto=texto,
        longitud_mensaje=len(texto),
    )
    db_session.add(msg)
    return msg


# ==================== PRUEBAS UNITARIAS DEL SERVICIO ====================


def test_elimina_conversacion_vieja_y_conserva_reciente(db_session):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    # retention_days = 90 -> cutoff: 2026-07-03 12:00:00

    conv_vieja = uuid.uuid4()
    _crear_mensaje(db_session, conv_vieja, now - timedelta(days=120), texto="Viejo 1")
    _crear_mensaje(db_session, conv_vieja, now - timedelta(days=95), texto="Viejo 2")

    conv_reciente = uuid.uuid4()
    _crear_mensaje(db_session, conv_reciente, now - timedelta(days=10), texto="Reciente 1")
    _crear_mensaje(db_session, conv_reciente, now - timedelta(days=2), texto="Reciente 2")

    db_session.commit()

    resultado = purge_old_chat_logs(db_session, retention_days=90, now=now)

    assert resultado["success"] is True
    assert resultado["conversaciones_eliminadas"] == 1
    assert resultado["mensajes_eliminados"] == 2
    assert resultado["dry_run"] is False

    # La conversación vieja fue purgada por completo
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_vieja).count() == 0

    # La conversación reciente se conserva íntegra
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_reciente).count() == 2


def test_conversacion_con_mensaje_reciente_no_se_borra(db_session):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    conv_mixta = uuid.uuid4()
    # Tiene mensajes muy antiguos pero el último es reciente
    _crear_mensaje(db_session, conv_mixta, now - timedelta(days=150), texto="Muy viejo")
    _crear_mensaje(db_session, conv_mixta, now - timedelta(days=100), texto="Viejo")
    _crear_mensaje(db_session, conv_mixta, now - timedelta(days=5), texto="Reciente")

    db_session.commit()

    resultado = purge_old_chat_logs(db_session, retention_days=90, now=now)

    assert resultado["success"] is True
    assert resultado["conversaciones_eliminadas"] == 0
    assert resultado["mensajes_eliminados"] == 0

    # No se borra ningún mensaje de la conversación (nunca mensajes sueltos)
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_mixta).count() == 3


def test_dry_run_reporta_conteos_y_no_elimina_nada(db_session):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    conv_vieja = uuid.uuid4()
    _crear_mensaje(db_session, conv_vieja, now - timedelta(days=110), texto="Viejo 1")
    _crear_mensaje(db_session, conv_vieja, now - timedelta(days=105), texto="Viejo 2")

    conv_reciente = uuid.uuid4()
    _crear_mensaje(db_session, conv_reciente, now - timedelta(days=5), texto="Reciente")

    db_session.commit()

    resultado = purge_old_chat_logs(db_session, retention_days=90, dry_run=True, now=now)

    assert resultado["success"] is True
    assert resultado["dry_run"] is True
    assert resultado["conversaciones_eliminadas"] == 1
    assert resultado["mensajes_eliminados"] == 2

    # En la base de datos no se ha borrado nada
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_vieja).count() == 2
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_reciente).count() == 1


def test_retention_days_cero_desactivado(db_session):
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    conv_vieja = uuid.uuid4()
    _crear_mensaje(db_session, conv_vieja, now - timedelta(days=200), texto="Viejo")
    db_session.commit()

    # retention_days = 0
    res_cero = purge_old_chat_logs(db_session, retention_days=0, now=now)
    assert res_cero["success"] is True
    assert res_cero["cutoff"] is None
    assert res_cero["conversaciones_eliminadas"] == 0
    assert res_cero["mensajes_eliminados"] == 0
    assert res_cero["detail"] == "Purga desactivada"

    # retention_days < 0
    res_negativo = purge_old_chat_logs(db_session, retention_days=-5, now=now)
    assert res_negativo["conversaciones_eliminadas"] == 0
    assert res_negativo["detail"] == "Purga desactivada"

    # No se eliminó nada
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_vieja).count() == 1


def test_purge_en_lotes_con_batch_size_uno(db_session, monkeypatch):
    monkeypatch.setattr(settings, "CHAT_LOG_PURGE_BATCH_SIZE", 1)

    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    # 3 conversaciones viejas con 2 mensajes cada una = 6 mensajes en total
    convs_viejas = [uuid.uuid4() for _ in range(3)]
    for cid in convs_viejas:
        _crear_mensaje(db_session, cid, now - timedelta(days=100), texto="Viejo A")
        _crear_mensaje(db_session, cid, now - timedelta(days=95), texto="Viejo B")

    # 1 conversación reciente
    conv_reciente = uuid.uuid4()
    _crear_mensaje(db_session, conv_reciente, now - timedelta(days=3), texto="Reciente")

    db_session.commit()

    resultado = purge_old_chat_logs(db_session, retention_days=90, now=now)

    assert resultado["success"] is True
    assert resultado["conversaciones_eliminadas"] == 3
    assert resultado["mensajes_eliminados"] == 6

    # Todas las conversaciones viejas fueron eliminadas a través de los lotes de tamaño 1
    for cid in convs_viejas:
        assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == cid).count() == 0

    # La reciente sigue intacta
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_reciente).count() == 1


# ==================== PRUEBAS DEL ENDPOINT POST /api/cron/purge-chat-logs ====================


def test_endpoint_purge_chat_logs_unauthorized_without_credentials(client):
    """Sin credenciales -> 401."""
    resp = client.post("/api/cron/purge-chat-logs")
    assert resp.status_code == 401
    data = resp.json()
    assert data["code"] == "UNAUTHORIZED_CRON"


def test_endpoint_purge_chat_logs_authorized_with_cron_secret_and_dry_run(client, db_session):
    """Con X-Cron-Secret válido y dry_run=true -> 200 y los conteos esperados sin borrar."""
    now = datetime.now(timezone.utc)
    conv_vieja = uuid.uuid4()
    _crear_mensaje(db_session, conv_vieja, now - timedelta(days=100), texto="Msg antiguo 1")
    _crear_mensaje(db_session, conv_vieja, now - timedelta(days=95), texto="Msg antiguo 2")

    conv_reciente = uuid.uuid4()
    _crear_mensaje(db_session, conv_reciente, now - timedelta(days=5), texto="Msg reciente")
    db_session.commit()

    headers = {"X-Cron-Secret": settings.CRON_SECRET}
    resp = client.post("/api/cron/purge-chat-logs?dry_run=true", headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["success"] is True
    assert data["dry_run"] is True
    assert data["conversaciones_eliminadas"] == 1
    assert data["mensajes_eliminados"] == 2

    # Verificar que nada fue borrado
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_vieja).count() == 2
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_reciente).count() == 1


def test_endpoint_purge_chat_logs_authorized_with_admin_jwt(client, db_session):
    """Con JWT de admin -> 200 y borra la conversación elegible."""
    now = datetime.now(timezone.utc)
    conv_vieja = uuid.uuid4()
    _crear_mensaje(db_session, conv_vieja, now - timedelta(days=100), texto="Msg a borrar")
    db_session.commit()

    token = create_access_token(subject="admin@kenpaku.pe")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/cron/purge-chat-logs", headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["success"] is True
    assert data["dry_run"] is False
    assert data["conversaciones_eliminadas"] == 1
    assert data["mensajes_eliminados"] == 1

    # Verificar que fue borrada
    assert db_session.query(ChatLog).filter(ChatLog.id_conversacion == conv_vieja).count() == 0


def test_endpoint_purge_chat_logs_validation_retention_days_zero(client):
    """retention_days=0 -> 422 (validación de ge=1 en Query parameter)."""
    headers = {"X-Cron-Secret": settings.CRON_SECRET}
    resp = client.post("/api/cron/purge-chat-logs?retention_days=0", headers=headers)
    assert resp.status_code == 422
