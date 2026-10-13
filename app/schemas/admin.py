from datetime import datetime
from decimal import Decimal
from typing import List, Optional
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

class ActionOrderItem(BaseModel):
    id: UUID
    codigo: str
    cliente_nombre: str
    estado: str
    total: Decimal
    motivo: str
    created_at: datetime
    fecha_limite_pago: Optional[datetime] = None


class ActionRequiredResponse(BaseModel):
    flete_por_cotizar: List[ActionOrderItem]
    voucher_por_validar: List[ActionOrderItem]
    pedidos_por_vencer: List[ActionOrderItem]
    reclamos_pendientes: int
    total_acciones: int