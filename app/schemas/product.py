from decimal import Decimal
from datetime import date
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings
from app.core.product_rules import infer_product_fields, validate_product_fields
from app.db.models import ProductAcabadoEnum, ProductCategoryEnum


def compute_stock_estado(stock: int) -> str:
    """Calcula el estado de stock derivado."""
    if stock <= 0:
        return "agotado"
    if stock <= settings.STOCK_LOW_THRESHOLD:
        return "pocas_unidades"
    return "disponible"


class ProductBase(BaseModel):
    nombre: str = Field(..., max_length=150)
    categoria: ProductCategoryEnum
    tipo: Optional[str] = Field(None, max_length=100)
    forma: Optional[str] = Field(None, max_length=50)
    acabado: Optional[ProductAcabadoEnum] = None
    medida: Optional[str] = None
    espesor: Optional[str] = None
    descripcion_corta: Optional[str] = None
    ficha_tecnica: Optional[str] = None
    precio_unitario: Decimal = Field(..., ge=0, decimal_places=2)
    sku: Optional[str] = Field(None, max_length=100)
    precio_base_usd: Optional[Decimal] = Field(None, ge=0, decimal_places=4)
    margen_pct: Optional[Decimal] = Field(None, ge=0, decimal_places=3)
    stock_disponible: int = Field(default=0, ge=0)
    imagen_url: Optional[str] = None
    activo: bool = True


class ProductCreate(ProductBase):
    @model_validator(mode="after")
    def validate_category_fields(self):
        values = infer_product_fields(self.categoria, self.model_dump())
        self.tipo = values.get("tipo")
        self.forma = values.get("forma")
        self.espesor = values.get("espesor")
        validate_product_fields(self.categoria, values)
        return self


class ProductUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=150)
    categoria: Optional[ProductCategoryEnum] = None
    tipo: Optional[str] = Field(None, max_length=100)
    forma: Optional[str] = Field(None, max_length=50)
    acabado: Optional[ProductAcabadoEnum] = None
    medida: Optional[str] = None
    espesor: Optional[str] = None
    descripcion_corta: Optional[str] = None
    ficha_tecnica: Optional[str] = None
    precio_unitario: Optional[Decimal] = Field(None, ge=0, decimal_places=2)
    sku: Optional[str] = Field(None, max_length=100)
    precio_base_usd: Optional[Decimal] = Field(None, ge=0, decimal_places=4)
    margen_pct: Optional[Decimal] = Field(None, ge=0, decimal_places=3)
    stock_disponible: Optional[int] = Field(None, ge=0)
    imagen_url: Optional[str] = None
    activo: Optional[bool] = None


class ProductStockPriceUpdate(BaseModel):
    stock_disponible: Optional[int] = Field(None, ge=0)
    precio_unitario: Optional[Decimal] = Field(None, ge=0, decimal_places=2)


class ProductActivoUpdate(BaseModel):
    activo: bool


class ProductResponse(BaseModel):
    id: UUID
    nombre: str
    categoria: ProductCategoryEnum
    tipo: Optional[str] = None
    forma: Optional[str] = None
    acabado: Optional[ProductAcabadoEnum] = None
    medida: Optional[str] = None
    espesor: Optional[str] = None
    descripcion_corta: Optional[str] = None
    ficha_tecnica: Optional[str] = None
    precio_unitario: Decimal
    stock_disponible: int
    stock_estado: str
    imagen_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ProductPaginatedResponse(BaseModel):
    items: List[ProductResponse]
    total: int
    page: int
    page_size: int


class AdminProductResponse(ProductResponse):
    activo: bool = True
    sku: Optional[str] = None
    precio_base_usd: Optional[Decimal] = None
    margen_pct: Optional[Decimal] = None
    tipo_cambio_usado: Optional[Decimal] = None
    margen_aplicado_pct: Optional[Decimal] = None
    fecha_tipo_cambio: Optional[date] = None
    fuente_tipo_cambio: Optional[str] = None


class AdminProductPaginatedResponse(BaseModel):
    items: List[AdminProductResponse]
    total: int
    page: int
    page_size: int


class CategorySummary(BaseModel):
    slug: str
    nombre: str
    descripcion: str
    total: int