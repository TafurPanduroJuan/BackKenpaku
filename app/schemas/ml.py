from typing import Optional

from pydantic import BaseModel, Field


class IntentRequest(BaseModel):
    """Esquema de entrada: campos que el MVP ya captura en chat_logs."""

    mensaje_texto: str = Field(..., min_length=1, max_length=500)
    timestamp: Optional[str] = Field(None, description="ISO 8601 en UTC; si falta se asume sin dato de horario")
    longitud_mensaje: Optional[int] = None
    contiene_palabra_clave_producto: Optional[bool] = None


class IntentResponse(BaseModel):
    """Esquema de salida: intención, confianza y acción sugerida para la interfaz."""

    intencion_id: int
    intencion: str
    probabilidad: float
    baja_confianza: bool
    accion: str
