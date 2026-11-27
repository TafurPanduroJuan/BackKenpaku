from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.models import ClaimEstadoEnum, ClaimTipoBienEnum, ClaimTipoEnum
from app.schemas.validators import (
    validar_documento,
    validar_nombre,
    validar_telefono,
)

class ClaimCreate(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=False)
    nombre: str = Field(..., min_length=2, max_length=150)
    documento: str = Field(..., min_length=8, max_length=20)
    telefono: str = Field(..., min_length=6, max_length=50)
    correo: EmailStr
    direccion: str = Field(..., min_length=5, max_length=200)
    tipo_bien: ClaimTipoBienEnum
    monto_reclamado: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("99999999.99"))
    @field_validator("monto_reclamado", mode="before")
    @classmethod
    def coerce_monto(cls, v):
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("El monto debe ser un número válido.")
    descripcion_bien: str = Field(..., min_length=3, max_length=500)
    tipo: ClaimTipoEnum
    detalle: str = Field(..., min_length=10, max_length=2000)
    pedido_consumidor: str = Field(..., min_length=5, max_length=1000)
    acepto_terminos: bool

    @field_validator("nombre")
    @classmethod
    def check_nombre(cls, v: str) -> str:
        return validar_nombre(v)

    @field_validator("telefono")
    @classmethod
    def check_telefono(cls, v: str) -> str:
        return validar_telefono(v)

    @field_validator("documento")
    @classmethod
    def check_documento(cls, v: str) -> str:
        return validar_documento(v)

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


class ClaimMessageResponse(BaseModel):
    id: UUID
    autor: str
    canal: str
    texto: str
    created_at: datetime

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
    fecha_limite: Optional[datetime] = None
    dias_habiles_restantes: Optional[int] = None
    mensajes_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ClaimAdminDetailResponse(ClaimDetailResponse):
    mensajes: list[ClaimMessageResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ClaimReplyCreate(BaseModel):
    texto: str = Field(..., min_length=10, max_length=4000)
    estado: Literal["en_proceso", "atendido"] = "en_proceso"
    enviar_correo: bool = True

    @field_validator("texto", mode="before")
    @classmethod
    def strip_texto(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return v


class ClaimStatusUpdate(BaseModel):
    estado: Literal["en_proceso", "atendido"]


class ClaimTrackingMessageResponse(BaseModel):
    autor: str
    texto: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClaimTrackingPublicResponse(BaseModel):
    codigo_seguimiento: str
    tipo: ClaimTipoEnum
    estado: ClaimEstadoEnum
    fecha: datetime
    fecha_limite: Optional[datetime] = None
    dias_habiles_restantes: Optional[int] = None
    descripcion_bien: str
    mensajes: list[ClaimTrackingMessageResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ClaimCustomerReply(BaseModel):
    codigo: str = Field(..., min_length=1)
    documento: str = Field(..., min_length=1)
    texto: str = Field(..., min_length=3, max_length=2000)
    conforme: Optional[bool] = None

    @field_validator("codigo", "documento", "texto", mode="before")
    @classmethod
    def strip_strings(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return v
