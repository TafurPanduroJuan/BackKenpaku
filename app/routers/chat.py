from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from app.core.rate_limit import check_chat_rate_limit
from app.core.rate_limit import get_real_client_ip
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.notification_service import notify_chat_handoff, notify_chat_purchase_intent
from app.services.rag_service import intent_is_compra, intent_is_reclamo, process_chat_rag

router = APIRouter(prefix="/api/chat", tags=["Chat RAG"])


@router.post(
    "",
    response_model=ChatResponse,
    dependencies=[Depends(check_chat_rate_limit)],
)
def chat_with_advisor(
    chat_in: ChatRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Endpoint del Asesor Virtual de IA con RAG.
    Responde consultas técnicas sobre tubos, perfiles, fierros y planchas.
    Si se detecta derivación humana, alerta al dueño por Telegram en segundo plano.
    El modelo de intención (APF3) agrega dos avisos: reclamo → derivación con motivo, y
    compra firme → alerta prioritaria al administrador (tiene precedencia si coinciden).
    """
    response = process_chat_rag(db, chat_in, client_ip=get_real_client_ip(request))
    intent = response.intent
    origen = f"Conversación {response.conversation_id}"

    if intent_is_compra(intent):
        background_tasks.add_task(
            notify_chat_purchase_intent,
            chat_in.message,
            origen,
            intent["probabilidad"],
        )
    elif response.handoff:
        motivo = None
        if intent_is_reclamo(intent):
            motivo = f"Reclamo/Soporte detectado por IA ({intent['probabilidad']:.0%} de confianza)"
        background_tasks.add_task(notify_chat_handoff, chat_in.message, origen, motivo)

    return response
