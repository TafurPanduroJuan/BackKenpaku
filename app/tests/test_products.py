from decimal import Decimal
import uuid
from app.db.models import Product, ProductCategoryEnum, ProductAcabadoEnum


def seed_test_products(db_session):
    p1 = Product(
        id=uuid.uuid4(),
        nombre="Tubo negro redondo 2 pulgadas",
        categoria=ProductCategoryEnum.tubos,
        acabado=ProductAcabadoEnum.negro,
        medida='2" x 6 m',
        espesor="2 mm",
        descripcion_corta="Tubo redondo de acero negro",
        ficha_tecnica="Ficha técnica de prueba para tubo negro redondo",
        precio_unitario=Decimal("128.90"),
        stock_disponible=15,
        imagen_url="http://example.com/img1.jpg",
        activo=True,
    )
    p2 = Product(
        id=uuid.uuid4(),
        nombre="Plancha LAF 1.5 mm",
        categoria=ProductCategoryEnum.planchas,
        acabado=ProductAcabadoEnum.negro,
        medida="1.20 x 2.40 m",
        espesor="1.5 mm",
        descripcion_corta="Plancha laminada en frio",
        ficha_tecnica="Ficha técnica de prueba para plancha LAF",
        precio_unitario=Decimal("195.00"),
        stock_disponible=0,  # Agotado
        imagen_url="http://example.com/img2.jpg",
        activo=True,
    )
    db_session.add_all([p1, p2])
    db_session.commit()
    return p1, p2


def test_get_products_list_and_pagination(client, db_session):
    p1, p2 = seed_test_products(db_session)
    response = client.get("/api/products")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 12


def test_get_products_search_filter(client, db_session):
    seed_test_products(db_session)
    response = client.get("/api/products?q=redondo")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert "Tubo negro" in data["items"][0]["nombre"]


def test_get_products_category_filter(client, db_session):
    seed_test_products(db_session)
    response = client.get("/api/products?categoria=planchas")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["categoria"] == "planchas"


def test_get_products_solo_stock_filter(client, db_session):
    seed_test_products(db_session)
    response = client.get("/api/products?solo_stock=true")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["stock_disponible"] > 0
    assert data["items"][0]["stock_estado"] == "disponible"


def test_get_product_detail_success(client, db_session):
    p1, _ = seed_test_products(db_session)
    response = client.get(f"/api/products/{p1.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(p1.id)
    assert data["nombre"] == p1.nombre
    assert data["stock_estado"] == "disponible"


def test_get_product_detail_not_found(client):
    random_id = uuid.uuid4()
    response = client.get(f"/api/products/{random_id}")
    assert response.status_code == 404
    data = response.json()
    assert data["code"] == "NOT_FOUND"
    assert data["detail"] == "Producto no encontrado"
