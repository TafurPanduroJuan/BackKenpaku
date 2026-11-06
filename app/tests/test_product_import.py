from decimal import Decimal
import io
import json
import uuid

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.models import (
    ExchangeRate,
    PricingSettings,
    Product,
    ProductAcabadoEnum,
    ProductCategoryEnum,
    ProductImportHistory,
    User,
    UserRolEnum,
)
from app.services import product_import_service
from app.services.fx_service import business_date


def seed_pricing(db_session):
    db_session.add(
        PricingSettings(
            id=1,
            margen_global_pct=Decimal("20"),
            costo_incluye_igv=False,
            redondeo=5,
        )
    )
    db_session.add(
        ExchangeRate(
            fecha=business_date(),
            moneda="USD",
            valor_venta=Decimal("3.75"),
            fuente="manual",
        )
    )
    db_session.commit()


def test_mapping_variants_ignore_unmapped_columns_and_preview_price(db_session):
    seed_pricing(db_session)
    table = (
        "Código proveedor\tDescripción\tPrice USD\tCategoría\tNotas internas\tStock\n"
        "PR-001\tTubo estructural\t10.00\ttubos\tNO GUARDAR\t8\n"
    )

    preview = product_import_service.build_preview(
        db_session, pasted_text=table, filename="Tabla pegada"
    )

    row = preview["rows"][0]
    assert preview["mapping"]["sku"] == "0"
    assert preview["mapping"]["nombre"] == "1"
    assert preview["mapping"]["precio_usd"] == "2"
    assert row["status"] == "NUEVO"
    assert row["precio_final_pen"] == "53.10"
    assert "NO GUARDAR" not in json.dumps(preview)


def test_xlsx_with_supplier_header_variants_parses(db_session):
    seed_pricing(db_session)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["cod", "description", "USD Price", "category"])
    sheet.append(["SKU-2", "Plancha LAF", 10, "planchas"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    preview = product_import_service.build_preview(
        db_session, data=buffer.getvalue(), filename="lista.xlsx"
    )

    assert preview["rows"][0]["status"] == "NUEVO"
    assert preview["rows"][0]["categoria"] == "planchas"


def test_category_finish_measure_and_thickness_are_inferred(db_session):
    seed_pricing(db_session)
    table = "SKU\tDescripción\tPrecio\nT-40\tTUBO CUADRADO NEGRO 40x40x1.5mm\t10\n"

    preview = product_import_service.build_preview(db_session, pasted_text=table)
    row = preview["rows"][0]

    assert row["status"] == "NUEVO"
    assert row["categoria"] == "tubos"
    assert row["acabado"] == "negro"
    assert row["medida"] == "40x40"
    assert row["espesor"] == "1.5 mm"
    assert set(row["inferidos"]) == {"categoria", "acabado", "medida", "espesor"}


def test_unrecognized_category_is_error_and_missing_category_can_be_reviewed(db_session):
    seed_pricing(db_session)
    table = "SKU\tNombre\tPrecio USD\tCategoria\nA\tProducto A\t10\tmetal desconocido\n"
    invalid = product_import_service.build_preview(db_session, pasted_text=table)
    assert invalid["rows"][0]["status"] == "ERROR"
    assert any("Categoria desconocida" in reason for reason in invalid["rows"][0]["motivos"])

    no_category = product_import_service.build_preview(
        db_session,
        pasted_text="SKU\tNombre\tPrecio USD\nB\tMaterial especial\t10\n",
    )
    assert no_category["rows"][0]["status"] == "REVISAR"
    fixed = product_import_service.build_preview(
        db_session,
        pasted_text="SKU\tNombre\tPrecio USD\nB\tMaterial especial\t10\n",
        category_overrides={"2": "accesorios"},
    )
    assert fixed["rows"][0]["status"] == "NUEVO"
    assert fixed["rows"][0]["categoria"] == "accesorios"


def test_invalid_price_and_empty_name_are_row_errors(db_session):
    seed_pricing(db_session)
    preview = product_import_service.build_preview(
        db_session,
        pasted_text="SKU\tNombre\tPrecio USD\tCategoria\nA\t\t10\ttubos\nB\tPlancha\tno es precio\tplanchas\n",
    )

    assert all(row["status"] == "ERROR" for row in preview["rows"])
    assert any("Nombre vacio" in reason for reason in preview["rows"][0]["motivos"])
    assert any("Precio USD invalido" in reason for reason in preview["rows"][1]["motivos"])


def test_preview_matches_by_sku_then_name_measure_thickness(db_session):
    seed_pricing(db_session)
    existing = Product(
        id=uuid.uuid4(),
        nombre="Tubo redondo 2 pulgadas",
        categoria=ProductCategoryEnum.tubos,
        acabado=ProductAcabadoEnum.negro,
        medida="2 pulgadas",
        espesor="2 mm",
        precio_unitario=Decimal("80.00"),
        stock_disponible=4,
        sku="EXIST-1",
        activo=True,
    )
    db_session.add(existing)
    db_session.commit()

    by_sku = product_import_service.build_preview(
        db_session,
        pasted_text="SKU\tNombre\tPrecio USD\tCategoria\nEXIST-1\tNuevo nombre\t12\ttubos\n",
    )
    by_details = product_import_service.build_preview(
        db_session,
        pasted_text="Nombre\tPrecio USD\tCategoria\tMedida\tEspesor\nTubo redondo 2 pulgadas\t12\ttubos\t2 pulgadas\t2 mm\n",
    )

    assert by_sku["rows"][0]["status"] == "ACTUALIZA"
    assert by_details["rows"][0]["status"] == "ACTUALIZA"
    assert by_details["rows"][0]["match_product_id"] == str(existing.id)


def test_reimport_updates_same_product_without_duplicate(db_session):
    seed_pricing(db_session)
    source = "SKU\tNombre\tPrecio USD\tCategoria\tMedida\tEspesor\nREIMPORT-1\tTubo cuadrado\t10\ttubos\t40x40\t1.5 mm\n"

    first, _ = product_import_service.commit_import(
        db_session, b"", "Tabla pegada", source, None, None, [], "todo", False, "admin@kenpaku.pe"
    )
    second, _ = product_import_service.commit_import(
        db_session, b"", "Tabla pegada", source, None, None, [], "todo", False, "admin@kenpaku.pe"
    )

    assert first.nuevos == 1 and first.actualizados == 0
    assert second.nuevos == 0 and second.actualizados == 1
    assert db_session.query(Product).filter(Product.sku == "REIMPORT-1").count() == 1
    product = db_session.query(Product).filter(Product.sku == "REIMPORT-1").one()
    assert product.precio_unitario == Decimal("53.10")
    assert product.imagen_url is None
    assert product.activo is False


def test_price_stock_update_preserves_other_fields_and_missing_stock(db_session):
    seed_pricing(db_session)
    existing = Product(
        id=uuid.uuid4(),
        nombre="Nombre original",
        categoria=ProductCategoryEnum.tubos,
        medida="40x40",
        espesor="1.5 mm",
        precio_unitario=Decimal("20.00"),
        precio_base_usd=Decimal("5.00"),
        stock_disponible=7,
        sku="ONLY-PRICE",
        activo=True,
    )
    db_session.add(existing)
    db_session.commit()
    source = "SKU\tNombre\tPrecio USD\tCategoria\nONLY-PRICE\tNombre nuevo\t12\tplanchas\n"

    history, _ = product_import_service.commit_import(
        db_session, b"", "Tabla pegada", source, None, None, [], "precio_stock", False, "admin@kenpaku.pe"
    )

    db_session.refresh(existing)
    assert history.actualizados == 1
    assert existing.nombre == "Nombre original"
    assert existing.categoria == ProductCategoryEnum.tubos
    assert existing.stock_disponible == 7
    assert existing.precio_unitario == Decimal("63.70")


def test_embedding_background_task_retries_and_persists_progress(monkeypatch):
    from app.services import product_import_service as import_service

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    product = Product(
        nombre="Tubo indexado",
        categoria=ProductCategoryEnum.tubos,
        precio_unitario=Decimal("10.00"),
        stock_disponible=0,
        activo=False,
    )
    history = ProductImportHistory(
        usuario_email="admin@kenpaku.pe",
        nuevos=1,
        actualizados=0,
        errores=0,
        indexing_status="queued",
        indexing_total=1,
    )
    db.add_all([product, history])
    db.commit()
    product_id = str(product.id)
    history_id = history.id
    db.close()

    attempts = {"count": 0}

    def fake_embedding(_product):
        attempts["count"] += 1
        return [0.0] * 1536 if attempts["count"] < 3 else [0.1] * 1536

    monkeypatch.setattr(import_service, "generate_product_embedding", fake_embedding)
    monkeypatch.setattr(import_service.time, "sleep", lambda _seconds: None)

    import_service.index_import_embeddings(history_id, [product_id], session_factory)

    check = session_factory()
    saved_product = check.query(Product).filter(Product.id == uuid.UUID(product_id)).one()
    saved_history = check.query(ProductImportHistory).filter(ProductImportHistory.id == history_id).one()
    assert attempts["count"] == 3
    assert saved_product.embedding[0] == 0.1
    assert saved_history.indexing_status == "completed"
    assert saved_history.indexing_completed == 1
    check.close()
    engine.dispose()


def _admin_headers(db_session):
    admin = User(
        email=f"import_{uuid.uuid4().hex[:8]}@kenpaku.pe",
        password_hash=get_password_hash("ImportTestAdmin2026!"),
        rol=UserRolEnum.admin,
        activo=True,
    )
    db_session.add(admin)
    db_session.commit()
    token = create_access_token(subject=admin.email)
    return {"Authorization": f"Bearer {token}"}


def test_preview_commit_history_and_no_image_filter(client, db_session, monkeypatch):
    seed_pricing(db_session)
    headers = _admin_headers(db_session)
    from app.routers import admin as admin_router

    monkeypatch.setattr(admin_router.product_import_service, "index_import_embeddings", lambda *args: None)
    source = "SKU\tNombre\tPrecio USD\tCategoria\nROUTE-1\tTubo ruta\t10\ttubos\n"
    preview = client.post(
        "/api/admin/products/import/preview",
        data={"pasted_text": source},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["rows"][0]["status"] == "NUEVO"

    committed = client.post(
        "/api/admin/products/import/commit",
        data={"pasted_text": source, "update_mode": "todo", "new_products_active": "false"},
        headers=headers,
    )
    assert committed.status_code == 200
    assert committed.json()["nuevos"] == 1
    assert committed.json()["indexing_status"] == "queued"

    history = client.get("/api/admin/products/import/history", headers=headers)
    assert history.status_code == 200
    assert history.json()["items"][0]["usuario_email"].startswith("import_")
    assert history.json()["items"][0]["nuevos"] == 1

    missing_image = client.get("/api/admin/products?sin_imagen=true", headers=headers)
    assert missing_image.status_code == 200
    assert any(item["sku"] == "ROUTE-1" for item in missing_image.json()["items"])


def test_admin_product_image_upload_updates_image_url(client, db_session, monkeypatch):
    headers = _admin_headers(db_session)
    product = Product(
        id=uuid.uuid4(),
        nombre="Producto con imagen manual",
        categoria=ProductCategoryEnum.tubos,
        precio_unitario=Decimal("20.00"),
        stock_disponible=1,
        activo=True,
    )
    db_session.add(product)
    db_session.commit()
    from app.routers import admin as admin_router

    monkeypatch.setattr(
        admin_router,
        "upload_product_image",
        lambda file_bytes, content_type: "https://storage.example/products/test.webp",
    )
    response = client.post(
        f"/api/admin/products/{product.id}/image",
        headers=headers,
        files={"image": ("product.webp", b"image-bytes", "image/webp")},
    )

    assert response.status_code == 200
    assert response.json()["imagen_url"] == "https://storage.example/products/test.webp"
    db_session.refresh(product)
    assert product.imagen_url == response.json()["imagen_url"]