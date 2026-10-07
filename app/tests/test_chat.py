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


def test_chat_out_of_catalog_returns_handoff_without_llm(client, db_session):
    """Prueba requerida: Consulta fuera de catálogo devuelve handoff=True sin llamar al LLM."""
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
