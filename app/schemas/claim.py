from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.db.models import ClaimTipoBienEnum, ClaimTipoEnum


class ClaimCreate(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=False)

    nombre: str = Field(..., min_length=2, max_length=150)
    documento: str = Field(..., pattern=r"^\d{8,12}$")
    telefono: str = Field(..., pattern=r"^9\d{8}$")
    correo: EmailStr
    direccion: str = Field(..., min_length=5, max_length=255)

    tipo_bien: ClaimTipoBienEnum
    monto_reclamado: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("99999999.99"))
    descripcion_bien: str = Field(..., min_length=3, max_length=500)

    tipo: ClaimTipoEnum
    detalle: str = Field(..., min_length=10, max_length=2000)
    pedido_consumidor: str = Field(..., min_length=5, max_length=1000)

    acepto_terminos: bool = Field(...)

    @field_validator("monto_reclamado", mode="before")
    @classmethod
    def coerce_monto(cls, v):
        if v is None or v == "":
            return None
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError("El monto debe ser un número válido.")

    @field_validator("acepto_terminos")
    @classmethod
    def must_accept_terms(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Debe aceptar los términos y condiciones para enviar su reclamo.")
        return v


class ClaimResponse(BaseModel):
    id: str
    numero_reclamo: str
    nombre: str
    documento: str
    correo: str
    telefono: str
    tipo: str
    tipo_bien: str
    monto_reclamado: Optional[Decimal]
    estado: str
    fecha_registro: str
    pdf_url: Optional[str] = None

    class Config:
        from_attributes = True