from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import (
    CategoryMargin,
    ExchangeRate,
    PricingSettings,
    Product,
)

CENT = Decimal("0.01")
IGV_RATE = Decimal("0.18")
DEFAULT_MARGIN_PCT = Decimal("20.000")
DEFAULT_ROUNDING_CENTS = 5


def get_pricing_settings(db: Session) -> PricingSettings:
    settings_row = db.query(PricingSettings).filter(PricingSettings.id == 1).first()
    if settings_row is None:
        settings_row = PricingSettings(
            id=1,
            margen_global_pct=DEFAULT_MARGIN_PCT,
            costo_incluye_igv=False,
            redondeo=DEFAULT_ROUNDING_CENTS,
        )
        db.add(settings_row)
        db.flush()
    return settings_row


def get_latest_exchange_rate(db: Session, moneda: str = "USD") -> Optional[ExchangeRate]:
    return (
        db.query(ExchangeRate)
        .filter(ExchangeRate.moneda == moneda)
        .order_by(ExchangeRate.fecha.desc(), ExchangeRate.created_at.desc(), ExchangeRate.id.desc())
        .first()
    )


def get_category_margins(db: Session) -> Dict[str, Decimal]:
    return {
        row.categoria: Decimal(str(row.margen_pct))
        for row in db.query(CategoryMargin).all()
    }


def resolve_margin_pct(
    product: Product,
    pricing_settings: PricingSettings,
    category_margins: Dict[str, Decimal],
) -> Decimal:
    if product.margen_pct is not None:
        return Decimal(str(product.margen_pct))
    category_margin = category_margins.get(product.categoria.value)
    if category_margin is not None:
        return Decimal(str(category_margin))
    return Decimal(str(pricing_settings.margen_global_pct))


def calculate_price_in_pen(
    precio_base_usd: Decimal,
    tipo_cambio: Decimal,
    margen_pct: Decimal,
    costo_incluye_igv: bool,
    redondeo_centimos: int = DEFAULT_ROUNDING_CENTS,
) -> Decimal:
    cost = Decimal(str(precio_base_usd))
    exchange_rate = Decimal(str(tipo_cambio))
    margin = Decimal(str(margen_pct))
    if cost < 0 or exchange_rate <= 0 or margin < 0 or redondeo_centimos < 1:
        raise ValueError("Los valores de costo, cambio, margen y redondeo deben ser válidos.")

    price = cost * exchange_rate * (Decimal("1") + margin / Decimal("100"))
    if not costo_incluye_igv:
        price *= Decimal("1") + IGV_RATE

    rounding_step = Decimal(redondeo_centimos) / Decimal("100")
    rounded = (price / rounding_step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (rounded * rounding_step).quantize(CENT, rounding=ROUND_HALF_UP)


def recalculate_usd_products(
    db: Session,
    exchange_rate: Optional[Decimal] = None,
) -> int:
    rate = exchange_rate
    if rate is None:
        latest = get_latest_exchange_rate(db)
        rate = Decimal(str(latest.valor_venta)) if latest else None
    if rate is None:
        return 0

    pricing_settings = get_pricing_settings(db)
    category_margins = get_category_margins(db)
    products = (
        db.query(Product)
        .filter(Product.precio_base_usd.is_not(None))
        .all()
    )
    for product in products:
        margin = resolve_margin_pct(product, pricing_settings, category_margins)
        product.precio_unitario = calculate_price_in_pen(
            Decimal(str(product.precio_base_usd)),
            Decimal(str(rate)),
            margin,
            pricing_settings.costo_incluye_igv,
            pricing_settings.redondeo,
        )
    return len(products)


def recalculate_product(
    db: Session,
    product: Product,
    exchange_rate: Optional[Decimal] = None,
) -> bool:
    if product.precio_base_usd is None:
        return False
    rate = exchange_rate
    if rate is None:
        latest = get_latest_exchange_rate(db)
        rate = Decimal(str(latest.valor_venta)) if latest else None
    if rate is None:
        raise ValueError("Configura un tipo de cambio antes de guardar productos con costo USD.")

    pricing_settings = get_pricing_settings(db)
    margin = resolve_margin_pct(product, pricing_settings, get_category_margins(db))
    product.precio_unitario = calculate_price_in_pen(
        Decimal(str(product.precio_base_usd)),
        Decimal(str(rate)),
        margin,
        pricing_settings.costo_incluye_igv,
        pricing_settings.redondeo,
    )
    return True


def get_product_pricing_details(
    db: Session,
    product: Product,
    exchange_rate: Optional[ExchangeRate] = None,
) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[object], Optional[str]]:
    if product.precio_base_usd is None:
        return None, None, None, None

    current_rate = exchange_rate or get_latest_exchange_rate(db)
    pricing_settings = get_pricing_settings(db)
    margin = resolve_margin_pct(product, pricing_settings, get_category_margins(db))
    if current_rate is None:
        return None, margin, None, None
    return (
        Decimal(str(current_rate.valor_venta)),
        margin,
        current_rate.fecha,
        current_rate.fuente,
    )