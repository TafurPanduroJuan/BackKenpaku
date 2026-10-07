from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Claim, ClaimEstadoEnum
from app.db.session import get_db
from app.schemas.claim import ClaimCreate, ClaimResponse

router = APIRouter(prefix="/api/claims", tags=["Claims"])


def generate_claim_code(db: Session) -> str:
    """Genera un código único de seguimiento con formato RC-2026-000001."""
    year = datetime.now(timezone.utc).year
    count = db.query(func.count(Claim.id)).scalar() or 0
    seq = count + 1
    code = f"RC-{year}-{seq:06d}"

    while db.query(Claim).filter(Claim.codigo_seguimiento == code).first():
        seq += 1
        code = f"RC-{year}-{seq:06d}"

    return code


@router.post("", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
def create_claim(claim_in: ClaimCreate, db: Session = Depends(get_db)):
    """Registra una reclamación o queja en el Libro de Reclamaciones virtual (Ley 29571)."""
    if not claim_in.acepto_terminos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": "Debe aceptar los términos y condiciones para enviar el reclamo.",
                "code": "VALIDATION_ERROR",
            },
        )

    codigo = generate_claim_code(db)

    claim = Claim(
        codigo_seguimiento=codigo,
        nombre=claim_in.nombre,
        documento=claim_in.documento,
        telefono=claim_in.telefono,
        correo=claim_in.correo,
        direccion=claim_in.direccion,
        tipo_bien=claim_in.tipo_bien,
        monto_reclamado=claim_in.monto_reclamado,
        descripcion_bien=claim_in.descripcion_bien,
        tipo=claim_in.tipo,
        detalle=claim_in.detalle,
        pedido_consumidor=claim_in.pedido_consumidor,
        estado=ClaimEstadoEnum.pendiente,
    )

    db.add(claim)
    db.commit()
    db.refresh(claim)

    return ClaimResponse(
        codigo_seguimiento=claim.codigo_seguimiento,
        fecha=claim.fecha,
    )
