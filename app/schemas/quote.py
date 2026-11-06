from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class QuoteLineInput(BaseModel):
    texto_original: str = Field(..., min_length=1, max_length=500)
    cantidad: Optional[Decimal] = Field(None, gt=0, max_digits=12, decimal_places=3)
    unidad: Optional[str] = Field(None, max_length=40)
    descripcion_normalizada: Optional[str] = Field(None, max_length=300)
    cantidad_asumida: bool = False


class QuoteRequest(BaseModel):
    texto: Optional[str] = Field(None, min_length=1, max_length=5000)
    items: Optional[List[QuoteLineInput]] = Field(None, max_length=50)
    conversation_id: Optional[UUID] = None

    @model_validator(mode="after")
    def require_source(self):
        if not self.texto and not self.items:
            raise ValueError("Envía un texto o una lista de ítems.")
        if self.items is not None and len(self.items) > 50:
            raise ValueError("Una proforma admite como máximo 50 ítems.")
        return self


class QuoteItemChoice(BaseModel):
    product_id: UUID


class QuoteCandidate(BaseModel):
    product_id: UUID
    nombre: str
    medida: Optional[str] = None
    espesor: Optional[str] = None
    acabado: Optional[str] = None
    precio_unitario: Decimal
    stock_disponible: int


class QuoteItemResponse(BaseModel):
    id: UUID
    texto_original: str
    product_id: Optional[UUID] = None
    nombre_snapshot: str
    medida_snapshot: Optional[str] = None
    cantidad: Decimal
    unidad: Optional[str] = None
    cantidad_asumida: bool
    precio_unitario_snapshot: Optional[Decimal] = None
    subtotal_linea: Optional[Decimal] = None
    estado_linea: str
    opciones: List[QuoteCandidate] = []


class QuoteResponse(BaseModel):
    id: UUID
    codigo: str
    subtotal: Decimal
    igv: Decimal
    total: Decimal
    tipo_cambio_usado: Optional[Decimal] = None
    fecha_emision: datetime
    valida_hasta: datetime
    estado: str
    parent_codigo: Optional[str] = None
    conversation_id: Optional[UUID] = None
    items: List[QuoteItemResponse]
    items_sin_cotizar: int
    aviso_validez: str


class QuoteSummary(BaseModel):
    codigo: str
    estado: str
    total: Decimal
    valida_hasta: datetime
    items_cotizados: int
    items_sin_cotizar: int


class QuoteComparisonLine(BaseModel):
    texto_original: str
    nombre_snapshot: str
    precio_anterior: Optional[Decimal] = None
    precio_nuevo: Optional[Decimal] = None
    diferencia: Optional[Decimal] = None
    estado: str


class QuoteRecalculateResponse(BaseModel):
    proforma: QuoteResponse
    total_anterior: Decimal
    total_nuevo: Decimal
    diferencia: Decimal
    diferencia_pct: Optional[Decimal] = None
    comparacion: List[QuoteComparisonLine]