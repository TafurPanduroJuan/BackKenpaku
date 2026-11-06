from datetime import timedelta
from decimal import Decimal
import uuid

from app.db.models import (
    CategoryMargin,
    ExchangeRate,
    PricingSettings,
    Product,
    ProductCategoryEnum,
    User,
    UserRolEnum,
)
from app.core.security import create_access_token, get_password_hash
from app.services import fx_service, pricing_service


def make_product(db_session, **overrides):
    values = {
        "id": uuid.uuid4(),
        "nombre": "Tubo de prueba",
        "categoria": ProductCategoryEnum.tubos,
        "precio_unitario": Decimal("90.00"),
        "stock_disponible": 5,
        "activo": True,
    }
    values.update(overrides)
    product = Product(**values)
    db_session.add(product)
    db_session.commit()
    return product


def test_price_formula_with_known_values():
    assert pricing_service.calculate_price_in_pen(
        Decimal("10.00"), Decimal("3.75"), Decimal("20"), True, 1
    ) == Decimal("45.00")
    assert pricing_service.calculate_price_in_pen(
        Decimal("10.00"), Decimal("3.75"), Decimal("20"), False, 1
    ) == Decimal("53.10")


def test_rounding_uses_configured_cent_increment():
    assert pricing_service.calculate_price_in_pen(
        Decimal("10.00"), Decimal("3.75"), Decimal("20"), True, 10
    ) == Decimal("45.00")
    assert pricing_service.calculate_price_in_pen(
        Decimal("10.02"), Decimal("3.75"), Decimal("20"), True, 10
    ) == Decimal("45.10")


def test_margin_priority_product_then_category_then_global(db_session):
    settings_row = PricingSettings(
        id=1,
        margen_global_pct=Decimal("20"),
        costo_incluye_igv=True,
        redondeo=1,
    )
    db_session.add(settings_row)
    db_session.add(CategoryMargin(categoria="tubos", margen_pct=Decimal("30")))
    product = make_product(db_session, margen_pct=Decimal("40"))

    assert pricing_service.resolve_margin_pct(product, settings_row, {"tubos": Decimal("30")}) == Decimal("40")
    product.margen_pct = None
    assert pricing_service.resolve_margin_pct(product, settings_row, {"tubos": Decimal("30")}) == Decimal("30")
    assert pricing_service.resolve_margin_pct(product, settings_row, {}) == Decimal("20")


def test_manual_rate_for_today_has_priority_over_api(db_session, monkeypatch):
    manual = fx_service.save_exchange_rate(
        db_session, Decimal("3.80"), "manual", fx_service.business_date()
    )
    monkeypatch.setattr(
        fx_service,
        "fetch_exchange_rate",
        lambda: (_ for _ in ()).throw(AssertionError("API should not be called")),
    )

    result = fx_service.refresh_exchange_rate_and_prices(db_session)

    assert result["success"] is True
    assert result["fuente"] == "manual"
    assert result["tipo_cambio"] == Decimal("3.80")
    assert manual.id is not None


def test_api_rate_is_saved_and_used(db_session, monkeypatch):
    monkeypatch.setattr(fx_service, "fetch_exchange_rate", lambda: Decimal("3.75"))
    product = make_product(db_session, precio_base_usd=Decimal("10.00"))

    result = fx_service.refresh_exchange_rate_and_prices(db_session)

    db_session.refresh(product)
    saved_rate = pricing_service.get_latest_exchange_rate(db_session)
    assert result["fuente"] == "api"
    assert saved_rate.valor_venta == Decimal("3.750000")
    assert product.precio_unitario == Decimal("53.10")


def test_api_failure_falls_back_to_last_saved_rate(db_session, monkeypatch):
    old_rate = ExchangeRate(
        fecha=fx_service.business_date() - timedelta(days=1),
        moneda="USD",
        valor_venta=Decimal("3.70"),
        fuente="api",
    )
    db_session.add(old_rate)
    product = make_product(db_session, precio_base_usd=Decimal("10.00"))
    monkeypatch.setattr(
        fx_service,
        "fetch_exchange_rate",
        lambda: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    result = fx_service.refresh_exchange_rate_and_prices(db_session)

    db_session.refresh(product)
    latest = pricing_service.get_latest_exchange_rate(db_session)
    assert result["success"] is True
    assert result["fuente"] == "ultimo_guardado"
    assert latest.valor_venta == Decimal("3.70")
    assert product.precio_unitario == Decimal("52.40")


def test_products_without_usd_cost_keep_manual_price(db_session):
    db_session.add(
        ExchangeRate(
            fecha=fx_service.business_date(),
            moneda="USD",
            valor_venta=Decimal("3.75"),
            fuente="manual",
        )
    )
    manual_product = make_product(db_session, precio_unitario=Decimal("123.45"))

    count = pricing_service.recalculate_usd_products(db_session)
    db_session.commit()
    db_session.refresh(manual_product)

    assert count == 0
    assert manual_product.precio_unitario == Decimal("123.45")


def _admin_headers(db_session):
    admin = User(
        email=f"pricing_{uuid.uuid4().hex[:8]}@kenpaku.pe",
        password_hash=get_password_hash("PricingTestAdmin2026!"),
        rol=UserRolEnum.admin,
        activo=True,
    )
    db_session.add(admin)
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(subject=admin.email)}"}


def test_admin_settings_recalculate_only_usd_products(client, db_session):
    headers = _admin_headers(db_session)
    usd_product = make_product(db_session, precio_base_usd=Decimal("10.00"))
    manual_product = make_product(db_session, precio_unitario=Decimal("123.45"))

    response = client.put(
        "/api/admin/pricing/settings",
        headers=headers,
        json={
            "margen_global_pct": 20,
            "costo_incluye_igv": True,
            "redondeo": 1,
            "margenes_por_categoria": [{"categoria": "tubos", "margen_pct": 25}],
            "tipo_cambio_manual": 3.75,
        },
    )

    assert response.status_code == 200
    assert response.json()["fuente_tipo_cambio"] == "manual"
    db_session.refresh(usd_product)
    db_session.refresh(manual_product)
    assert usd_product.precio_unitario == Decimal("46.88")
    assert manual_product.precio_unitario == Decimal("123.45")


def test_admin_products_expose_cost_rate_and_margin(client, db_session):
    headers = _admin_headers(db_session)
    db_session.add(
        ExchangeRate(
            fecha=fx_service.business_date(),
            moneda="USD",
            valor_venta=Decimal("3.75"),
            fuente="manual",
        )
    )
    product = make_product(db_session, precio_base_usd=Decimal("10.00"))

    response = client.get("/api/admin/products", headers=headers)

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == str(product.id))
    assert Decimal(str(item["precio_base_usd"])) == Decimal("10.0000")
    assert Decimal(str(item["tipo_cambio_usado"])) == Decimal("3.750000")
    assert Decimal(str(item["margen_aplicado_pct"])) == Decimal("20.000")


def test_admin_quick_price_cannot_override_usd_priced_product(client, db_session):
    headers = _admin_headers(db_session)
    db_session.add(
        ExchangeRate(
            fecha=fx_service.business_date(),
            moneda="USD",
            valor_venta=Decimal("3.75"),
            fuente="manual",
        )
    )
    product = make_product(db_session, precio_base_usd=Decimal("10.00"))

    response = client.patch(
        f"/api/admin/products/{product.id}/stock-precio",
        headers=headers,
        json={"precio_unitario": 999},
    )

    assert response.status_code == 409


def test_pricing_cron_is_protected_and_refreshes(client, db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(fx_service, "fetch_exchange_rate", lambda: Decimal("3.91"))
    unauthorized = client.post("/api/cron/refresh-pricing")
    assert unauthorized.status_code == 401

    response = client.post(
        "/api/cron/refresh-pricing",
        headers={"X-Cron-Secret": settings.CRON_SECRET},
    )

    assert response.status_code == 200
    assert response.json()["fuente"] == "api"
    assert response.json()["tipo_cambio"] == "3.91"