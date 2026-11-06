import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.services.cron_service import process_scheduled_tasks
from app.services.fx_service import refresh_exchange_rate_and_prices

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cron", tags=["cron"])


def verify_cron_access(
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
    cron_secret_query: Optional[str] = Query(None, alias="cron_secret"),
    auth_header: Optional[str] = Header(None, alias="Authorization"),
) -> Dict[str, str]:
    """
    Verifica que la petición proceda de un origen autorizado:
    1. Cabecera secreta X-Cron-Secret configurada en el cron externo (GitHub Actions / cron-job.org).
    2. Query param ?cron_secret= (útil para webhooks simples o pruebas de navegador).
    3. Token JWT de Administrador en cabecera Authorization (para disparador manual desde Admin).
    """
    # 1. Secreto de Cron
    provided_secret = x_cron_secret or cron_secret_query
    if provided_secret and provided_secret.strip() == settings.CRON_SECRET:
        return {"authorized_by": "cron_secret"}

    # 2. Token JWT de Admin
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        payload = decode_access_token(token)
        if payload and payload.get("sub"):
            return {"authorized_by": "admin_jwt"}

    logger.warning("[CRON UNAUTHORIZED] Intento de ejecución de tareas programadas sin credenciales válidas.")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "detail": "Acceso no autorizado al servicio de tareas programadas. Se requiere cabecera X-Cron-Secret válida o token de administrador.",
            "code": "UNAUTHORIZED_CRON",
        },
    )


@router.post("/process-scheduled-tasks")
def run_scheduled_tasks(
    simulate_hours: int = Query(
        0, ge=0, description="Horas a simular hacia el futuro (para pruebas y demostraciones)"
    ),
    auth: Dict[str, str] = Depends(verify_cron_access),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Endpoint principal para ejecución de tareas programadas del sistema Kenpaku:
    - Despierta el servicio web en Render si está dormido.
    - Realiza ping keep-alive a la base de datos Supabase.
    - Envía recordatorios de 24h a clientes pendientes.
    - Cancela pedidos que superaron las 48h y restituye stock reservado.
    """
    logger.info(
        f"[CRON TRIGGER] Ejecutando tareas programadas (autorizado por: {auth['authorized_by']}, simulación: +{simulate_hours}h)"
    )
    result = process_scheduled_tasks(db, simulate_hours=simulate_hours)
    return result


@router.post("/refresh-pricing")
def run_pricing_refresh(
    auth: Dict[str, str] = Depends(verify_cron_access),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Actualiza el tipo de cambio del día y recalcula productos con costo USD."""
    logger.info(
        "[CRON PRICING] Actualizando precios (autorizado por: %s)",
        auth["authorized_by"],
    )
    result = refresh_exchange_rate_and_prices(db)
    if not result["success"]:
        raise HTTPException(status_code=503, detail=result["detail"])
    return result


@router.get("/status")
def get_cron_configuration():
    """Retorna información del estado de configuración del cron (público informativo)."""
    return {
        "status": "active",
        "reminder_hours": settings.CRON_REMINDER_HOURS,
        "expiration_hours": settings.CRON_EXPIRATION_HOURS,
        "keepalive_support": True,
        "instructions": "Invoque POST /api/cron/process-scheduled-tasks con cabecera X-Cron-Secret o sesión de admin.",
    }
