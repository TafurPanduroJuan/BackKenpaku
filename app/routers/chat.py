from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.rate_limit import check_chat_rate_limit
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag_service import process_chat_rag

router = APIRouter(prefix="/api/chat", tags=["Chat RAG"])


@router.post(
    "",
    response_model=ChatResponse,
    dependencies=[Depends(check_chat_rate_limit)],
)
def chat_with_advisor(chat_in: ChatRequest, db: Session = Depends(get_db)):
    """
    Endpoint del Asesor Virtual de IA con RAG.
    Responde consultas técnicas sobre tubos, perfiles, fierros y planchas.
    """
    return process_chat_rag(db, chat_in)
