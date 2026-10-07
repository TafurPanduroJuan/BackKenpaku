from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.db.models import ChatRolEnum


class DashboardMetrics(BaseModel):
    pedidos_pendientes: int
    pedidos_hoy: int
    consultas_chat_hoy: int
    porcentaje_derivadas: float


class ChatLogResponse(BaseModel):
    id: UUID
    id_conversacion: UUID
    timestamp: datetime
    rol: ChatRolEnum
    mensaje_texto: str
    longitud_mensaje: int
    contiene_palabra_clave_producto: bool
    intencion_etiquetada: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
