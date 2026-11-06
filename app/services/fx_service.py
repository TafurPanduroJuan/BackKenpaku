import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ExchangeRate
from app.services.pricing_service import get_latest_exchange_rate, recalculate_usd_products

logger = logging.getLogger(__name__)
BUSINESS_TIMEZONE = timezone(-timedelta(hours=5))


def business_date() -> date:
    return datetime.now(BUSINESS_TIMEZONE).date()


def _extract_rate(payload: Any) -> Decimal:
    preferred_keys = (
        "valor_venta",
        "valorVenta",
        "venta",
        "sell_rate",
        "sell",
        "exchange_rate",
        "rate",
        "USDPEN",
        "USD_PEN",
        "PEN",
    )
    if isinstance(payload, dict):
        for key in preferred_keys:
            if key in payload:
                try:
                    value = Decimal(str(payload[key]))
                except (InvalidOperation, TypeError, ValueError):
                    continue
                if value > 0:
                    return value
        for key in ("data", "result", "rates", "currency"):
            if key in payload:
                try:
                    return _extract_rate(payload[key])
                except ValueError:
                    pass
    raise ValueError("La respuesta FX no contiene una tasa de venta USD/PEN válida.")


def fetch_exchange_rate() -> Decimal:
    if not settings.FX_API_URL:
        raise RuntimeError("FX_API_URL no está configurada.")

    headers = {"Accept": "application/json"}
    if settings.FX_API_KEY:
        headers["x-api-key"] = settings.FX_API_KEY

    response = httpx.get(settings.FX_API_URL, headers=headers, timeout=12)
    response.raise_for_status()
    payload = json.loads(response.text, parse_float=Decimal, parse_int=Decimal)
    return _extract_rate(payload)


def save_exchange_rate(
    db: Session,
    rate: Decimal,
    fuente: str,
    fecha: Optional[date] = None,
) -> ExchangeRate:
    value = Decimal(str(rate))
    if value <= 0:
        raise ValueError("El tipo de cambio debe ser mayor que cero.")
    row = ExchangeRate(
        fecha=fecha or business_date(),
        moneda="USD",
        valor_venta=value,
        fuente=fuente,
    )
    db.add(row)
    db.flush()
    return row


def set_manual_exchange_rate(db: Session, rate: Decimal) -> ExchangeRate:
    row = save_exchange_rate(db, rate, "manual")
    recalculate_usd_products(db, Decimal(str(row.valor_venta)))
    return row


def refresh_exchange_rate_and_prices(db: Session) -> dict:
    today = business_date()
    manual_today = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.fecha == today,
            ExchangeRate.moneda == "USD",
            ExchangeRate.fuente == "manual",
        )
        .order_by(ExchangeRate.created_at.desc(), ExchangeRate.id.desc())
        .first()
    )

    used_source = "manual"
    if manual_today is not None:
        used_rate = Decimal(str(manual_today.valor_venta))
    else:
        try:
            used_rate = fetch_exchange_rate()
            used_source = "api"
            save_exchange_rate(db, used_rate, used_source, today)
        except Exception as exc:
            logger.warning("No se pudo consultar la API FX; se usará la última tasa guardada: %s", exc)
            previous = get_latest_exchange_rate(db)
            if previous is None:
                db.rollback()
                return {
                    "success": False,
                    "fuente": None,
                    "tipo_cambio": None,
                    "productos_recalculados": 0,
                    "detail": "No hay tasa disponible en la API ni en el historial.",
                }
            used_rate = Decimal(str(previous.valor_venta))
            used_source = "ultimo_guardado"
            save_exchange_rate(db, used_rate, used_source, today)

    products_recalculated = recalculate_usd_products(db, used_rate)
    db.commit()
    return {
        "success": True,
        "fuente": used_source,
        "tipo_cambio": used_rate,
        "fecha": today,
        "productos_recalculados": products_recalculated,
    }