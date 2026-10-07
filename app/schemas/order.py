from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ClienteInfo(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=150)
    telefono: str = Field(..., min_length=6, max_length=50)
    correo: EmailStr


class OrderItemCreate(BaseModel):
    product_id: UUID
    cantidad: int = Field(..., gt=0)


class OrderCreate(BaseModel):
    cliente: ClienteInfo
    direccion: Optional[str] = None
    recojo_en_tienda: bool = False
    observaciones: Optional[str] = None
    acepto_privacidad: bool
    items: List[OrderItemCreate] = Field(..., min_length=1)

    @field_validator("acepto_privacidad")
    @classmethod
    def validate_privacy(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError(
                "Debe aceptar la política de privacidad para procesar el pedido."
            )
        return v


class OrderItemResponse(BaseModel):
    nombre: str
    cantidad: int
    precio_unitario: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: UUID
    codigo: str
    estado: str
    subtotal: Decimal
    igv: Decimal
    total: Decimal
    items: List[OrderItemResponse]
    whatsapp_url: str

    model_config = ConfigDict(from_attributes=True)


class OrderDetailResponse(BaseModel):
    id: UUID
    codigo: str
    cliente_nombre: str
    cliente_telefono: str
    cliente_correo: str
    direccion: Optional[str] = None
    recojo_en_tienda: bool
    observaciones: Optional[str] = None
    estado: str
    subtotal: Decimal
    igv: Decimal
    total: Decimal
    acepto_privacidad: bool
    created_at: datetime
    items: List[OrderItemResponse]

    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    estado: str
