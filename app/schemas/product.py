from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
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
    acabado: Optional[ProductAcabadoEnum] = None
    medida: Optional[str] = None
    espesor: Optional[str] = None
    descripcion_corta: Optional[str] = None
    ficha_tecnica: Optional[str] = None
    precio_unitario: Decimal = Field(..., ge=0, decimal_places=2)
    stock_disponible: int = Field(default=0, ge=0)
    imagen_url: Optional[str] = None
    activo: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=150)
    categoria: Optional[ProductCategoryEnum] = None
    acabado: Optional[ProductAcabadoEnum] = None
    medida: Optional[str] = None
    espesor: Optional[str] = None
    descripcion_corta: Optional[str] = None
    ficha_tecnica: Optional[str] = None
    precio_unitario: Optional[Decimal] = Field(None, ge=0, decimal_places=2)
    stock_disponible: Optional[int] = Field(None, ge=0)
    imagen_url: Optional[str] = None
    activo: Optional[bool] = None


class ProductStockPriceUpdate(BaseModel):
    stock_disponible: Optional[int] = Field(None, ge=0)
    precio_unitario: Optional[Decimal] = Field(None, ge=0, decimal_places=2)


class ProductResponse(BaseModel):
    id: UUID
    nombre: str
    categoria: ProductCategoryEnum
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


class CategorySummary(BaseModel):
    slug: str
    nombre: str
    descripcion: str
    total: int
