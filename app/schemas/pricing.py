from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.db.models import ProductCategoryEnum


class CategoryMarginInput(BaseModel):
    categoria: ProductCategoryEnum
    margen_pct: Decimal = Field(ge=0, decimal_places=3)


class PricingSettingsUpdate(BaseModel):
    margen_global_pct: Decimal = Field(ge=0, le=500, decimal_places=3)
    costo_incluye_igv: bool
    redondeo: int = Field(ge=1, le=100)
    margenes_por_categoria: List[CategoryMarginInput] = Field(default_factory=list)
    tipo_cambio_manual: Optional[Decimal] = Field(None, gt=0, decimal_places=6)


class PricingSettingsResponse(BaseModel):
    margen_global_pct: Decimal
    costo_incluye_igv: bool
    redondeo: int
    margenes_por_categoria: List[CategoryMarginInput]
    tipo_cambio_actual: Optional[Decimal] = None
    fecha_tipo_cambio: Optional[date] = None
    fuente_tipo_cambio: Optional[str] = None