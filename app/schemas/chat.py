from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.product import ProductResponse


class ChatRequest(BaseModel):
    conversation_id: Optional[UUID] = None
    message: str = Field(..., min_length=1, max_length=500)
    product_id: Optional[UUID] = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    reply: str
    products: List[ProductResponse] = []
    handoff: bool = False
    whatsapp_url: Optional[str] = None
    generated_by_ai: bool = True
