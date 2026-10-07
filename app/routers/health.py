from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health")
def get_health():
    """Endpoint de verificación de salud del servidor."""
    return {"status": "ok"}
