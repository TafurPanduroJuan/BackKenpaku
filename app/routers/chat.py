from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.core.rate_limit import check_chat_rate_limit
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.notification_service import notify_chat_handoff
from app.services.rag_service import process_chat_rag

router = APIRouter(prefix="/api/chat", tags=["Chat RAG"])


@router.post(
    "",
    response_model=ChatResponse,
    dependencies=[Depends(check_chat_rate_limit)],
)
def chat_with_advisor(
    chat_in: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Endpoint del Asesor Virtual de IA con RAG.
    Responde consultas técnicas sobre tubos, perfiles, fierros y planchas.
    Si se detecta derivación humana, alerta al dueño por Telegram en segundo plano.
    """
    response = process_chat_rag(db, chat_in)

    if response.handoff:
        background_tasks.add_task(
            notify_chat_handoff,
            chat_in.message,
            f"Conversación {response.conversation_id}",
        )

    return response
