from fastapi import APIRouter, Depends

from app.core.rate_limit import check_ml_rate_limit
from app.schemas.ml import IntentRequest, IntentResponse
from app.services.intent_model import predecir_intencion

router = APIRouter(prefix="/api/ml", tags=["Machine Learning"])


@router.post(
    "/intent",
    response_model=IntentResponse,
    dependencies=[Depends(check_ml_rate_limit)],
)
def clasificar_intencion(payload: IntentRequest):
    """Clasifica la intención de un mensaje (0 consulta, 1 cotización, 2 reclamo, 3 compra)."""
    return predecir_intencion(payload.model_dump())