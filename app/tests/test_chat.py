from decimal import Decimal
import uuid
from app.core.security import create_access_token, get_password_hash
from app.db.models import ChatLog, Product, ProductCategoryEnum, ProductAcabadoEnum, User, UserRolEnum
from app.services.embeddings import generate_product_embedding_text, get_embedding


def seed_test_chat_product(db_session):
    text = generate_product_embedding_text(
        nombre='Tubo negro redondo 2" x 6 m',
        categoria="tubos",
        acabado="negro",
        medida='2" x 6 m',
        espesor="2 mm",
        ficha_tecnica="Ficha técnica de prueba para tubo negro redondo",
    )
    product = Product(
        id=uuid.uuid4(),
        nombre='Tubo negro redondo 2" x 6 m',
        categoria=ProductCategoryEnum.tubos,
        acabado=ProductAcabadoEnum.negro,
        medida='2" x 6 m',
        espesor="2 mm",
        descripcion_corta="Tubo redondo de acero negro",
        ficha_tecnica="Ficha técnica de prueba para tubo negro redondo",
        precio_unitario=Decimal("128.90"),
        stock_disponible=15,
        activo=True,
        embedding=get_embedding(text),
    )
    db_session.add(product)
    db_session.commit()
    return product


def test_chat_out_of_catalog_without_api_key_returns_handoff(client, db_session):
    """Sin API key del LLM, una consulta fuera de catálogo deriva a un asesor (handoff=True)."""
    payload = {
        "message": "Venden pintura de autos o computadoras de escritorio?"
    }
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["handoff"] is True
    assert data["products"] == []
    assert "https://wa.me/" in data["whatsapp_url"]
    assert data["generated_by_ai"] is True

    # Verificar que se haya guardado el log anonimizado
    log = db_session.query(ChatLog).filter(ChatLog.id_conversacion == uuid.UUID(data["conversation_id"])).first()
    assert log is not None


def test_chat_with_catalog_product_query(client, db_session):
    product = seed_test_chat_product(db_session)
    payload = {
        "message": 'Tienen tubo negro redondo de 2" de espesor 2mm?'
    }
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "conversation_id" in data
    assert len(data["products"]) > 0
    assert data["products"][0]["nombre"] == product.nombre
    assert data["generated_by_ai"] is True


def test_admin_reindex_embeddings(client, db_session):
    admin = User(
        email="admin@kenpaku.pe",
        password_hash=get_password_hash("AdminKenpaku2026!"),
        rol=UserRolEnum.admin,
        activo=True,
    )
    db_session.add(admin)
    seed_test_chat_product(db_session)
    db_session.commit()

    token = create_access_token(subject=admin.email)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post("/api/admin/knowledge/reindex", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == "SUCCESS"
    assert data["total_reindexed"] >= 1


def test_chat_out_of_catalog_still_calls_llm_for_general_guidance(client, db_session, monkeypatch):
    """Con API key, una consulta sin coincidencias ya no deriva de inmediato: el LLM orienta con contexto vacío."""
    from app.core.config import settings
    from app.services import llm_service

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-key")
    captured = {}

    def fake_call(contents):
        captured["contents"] = contents
        return {"candidates": [{"content": {"parts": [{"text": "Para una cerca podrías usar malla o tubos."}]}}]}

    monkeypatch.setattr(llm_service, "_call_with_fallback", fake_call)

    response = client.post("/api/chat", json={"message": "Quiero hacer una cerca para mi terreno"})
    assert response.status_code == 200
    data = response.json()
    assert data["reply"].startswith("Para una cerca")
    assert data["products"] == []
    assert data["handoff"] is False
    assert llm_service.NO_MATCH_CONTEXT in captured["contents"][-1]["parts"][0]["text"]


def test_whatsapp_handoff_url_includes_conversation_summary():
    from urllib.parse import unquote
    from app.services.whatsapp import build_whatsapp_handoff_url

    url = build_whatsapp_handoff_url("necesito 50 metros", ["quiero hacer una cerca", "de 2 m de alto"])
    text = unquote(url)
    assert "necesito 50 metros" in text
    assert "quiero hacer una cerca" in text and "de 2 m de alto" in text