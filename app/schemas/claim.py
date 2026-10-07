from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.models import ClaimEstadoEnum, ClaimTipoBienEnum, ClaimTipoEnum


class ClaimCreate(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=150)
    documento: str = Field(..., min_length=8, max_length=20)
    telefono: str = Field(..., min_length=6, max_length=50)
    correo: EmailStr
    direccion: str = Field(..., min_length=5)
    tipo_bien: ClaimTipoBienEnum
    monto_reclamado: Optional[Decimal] = Field(None, ge=0)
    descripcion_bien: str = Field(..., min_length=3)
    tipo: ClaimTipoEnum
    detalle: str = Field(..., min_length=10)
    pedido_consumidor: str = Field(..., min_length=5)
    acepto_terminos: bool

    @field_validator("acepto_terminos")
    @classmethod
    def validate_terms(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError(
                "Debe aceptar los términos y condiciones para registrar el reclamo."
            )
        return v


class ClaimResponse(BaseModel):
    codigo_seguimiento: str
    fecha: datetime

    model_config = ConfigDict(from_attributes=True)


class ClaimDetailResponse(BaseModel):
    id: UUID
    codigo_seguimiento: str
    nombre: str
    documento: str
    telefono: str
    correo: str
    direccion: str
    tipo_bien: ClaimTipoBienEnum
    monto_reclamado: Optional[Decimal] = None
    descripcion_bien: str
    tipo: ClaimTipoEnum
    detalle: str
    pedido_consumidor: str
    fecha: datetime
    estado: ClaimEstadoEnum

    model_config = ConfigDict(from_attributes=True)
