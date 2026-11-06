from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.product import ProductResponse
from app.schemas.quote import QuoteSummary


class ChatRequest(BaseModel):
    conversation_id: Optional[UUID] = None
    message: str = Field(..., min_length=1, max_length=1500)
    product_id: Optional[UUID] = None
    pending_quote_text: Optional[str] = Field(None, max_length=5000)


class ChatResponse(BaseModel):
    conversation_id: UUID
    reply: str
    products: List[ProductResponse] = []
    handoff: bool = False
    whatsapp_url: Optional[str] = None
    generated_by_ai: bool = True
    quote: Optional[QuoteSummary] = None
    pending_quote_text: Optional[str] = None
    quote_missing_fields: List[str] = []
