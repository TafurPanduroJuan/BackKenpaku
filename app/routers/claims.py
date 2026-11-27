from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.rate_limit import check_tracking_rate_limit
from app.db.models import Claim, ClaimEstadoEnum, ClaimMessage
from app.db.session import get_db
from app.schemas.claim import (
    ClaimCreate,
    ClaimCustomerReply,
    ClaimResponse,
    ClaimTrackingMessageResponse,
    ClaimTrackingPublicResponse,
)
from app.services.business_days import (
    add_business_days,
    claim_fecha_limite,
    dias_habiles_restantes,
)
from app.services.notification_service import (
    notify_claim_created,
    notify_claim_customer_reply,
)

router = APIRouter(prefix="/api/claims", tags=["Claims"])


def generate_claim_code(db: Session) -> str:
    """Genera un código único de seguimiento con formato RC-YYYY-000001 usando secuencia atómica en PostgreSQL."""
    year = datetime.now(timezone.utc).year
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(text("CREATE SEQUENCE IF NOT EXISTS claim_code_seq;"))
        seq_val = db.execute(text("SELECT nextval('claim_code_seq');")).scalar()
        code = f"RC-{year}-{seq_val:06d}"
        while db.query(Claim).filter(Claim.codigo_seguimiento == code).first():
            seq_val = db.execute(text("SELECT nextval('claim_code_seq');")).scalar()
            code = f"RC-{year}-{seq_val:06d}"
        return code

    count = db.query(func.count(Claim.id)).scalar() or 0
    seq = count + 1
    code = f"RC-{year}-{seq:06d}"

    while db.query(Claim).filter(Claim.codigo_seguimiento == code).first():
        seq += 1
        code = f"RC-{year}-{seq:06d}"

    return code


@router.post("", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
def create_claim(
    claim_in: ClaimCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
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
    fecha = datetime.now(timezone.utc)

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
        fecha=fecha,
        fecha_limite=add_business_days(fecha, 15),
    )

    db.add(claim)
    db.commit()
    db.refresh(claim)

    background_tasks.add_task(notify_claim_created, claim)

    return ClaimResponse(
        codigo_seguimiento=claim.codigo_seguimiento,
        fecha=claim.fecha,
    )


def resolve_tracking_claim(
    db: Session,
    codigo: Optional[str] = None,
    documento: Optional[str] = None,
) -> Claim:
    """
    Resuelve de forma segura un reclamo para consulta pública.
    Requiere código y documento. Ante cualquier error devuelve el mismo 404 genérico.
    """
    if not codigo or not documento or not codigo.strip() or not documento.strip():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró ningún reclamo con los datos proporcionados.",
        )

    codigo_clean = codigo.strip().upper()
    doc_clean = documento.strip()

    claim = db.query(Claim).filter(Claim.codigo_seguimiento == codigo_clean).first()
    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró ningún reclamo con los datos proporcionados.",
        )

    if (claim.documento or "").strip() != doc_clean:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró ningún reclamo con los datos proporcionados.",
        )

    return claim


def claim_to_tracking_response(claim: Claim) -> ClaimTrackingPublicResponse:
    fl = claim_fecha_limite(claim)
    estado_val = claim.estado.value if hasattr(claim.estado, "value") else str(claim.estado)
    dias_rest = None if estado_val == ClaimEstadoEnum.atendido.value else dias_habiles_restantes(fl)

    msgs = [
        ClaimTrackingMessageResponse(
            autor=m.autor,
            texto=m.texto,
            created_at=m.created_at,
        )
        for m in (claim.mensajes or [])
        if m.autor != "sistema"
    ]

    return ClaimTrackingPublicResponse(
        codigo_seguimiento=claim.codigo_seguimiento,
        tipo=claim.tipo,
        estado=claim.estado,
        fecha=claim.fecha,
        fecha_limite=fl,
        dias_habiles_restantes=dias_rest,
        descripcion_bien=claim.descripcion_bien,
        mensajes=msgs,
    )


@router.get(
    "/tracking",
    response_model=ClaimTrackingPublicResponse,
    dependencies=[Depends(check_tracking_rate_limit)],
)
def get_claim_public_tracking(
    codigo: str = Query(..., description="Código de seguimiento del reclamo"),
    documento: str = Query(..., description="Documento de identidad del titular"),
    db: Session = Depends(get_db),
):
    """Consulta el estado público y los mensajes de un reclamo."""
    claim = resolve_tracking_claim(db, codigo, documento)
    return claim_to_tracking_response(claim)


@router.post(
    "/tracking/respuesta",
    response_model=ClaimTrackingPublicResponse,
    dependencies=[Depends(check_tracking_rate_limit)],
)
def reply_to_claim_public(
    reply_in: ClaimCustomerReply,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Permite al titular responder al reclamo desde el portal público."""
    claim = resolve_tracking_claim(db, reply_in.codigo, reply_in.documento)

    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    mensajes_recientes_count = (
        db.query(func.count(ClaimMessage.id))
        .filter(
            ClaimMessage.claim_id == claim.id,
            ClaimMessage.autor == "cliente",
            ClaimMessage.created_at >= since_24h,
        )
        .scalar()
        or 0
    )
    if mensajes_recientes_count >= 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Ha alcanzado el límite máximo de 10 mensajes en 24 horas para este reclamo.",
        )

    estado_val = claim.estado.value if hasattr(claim.estado, "value") else str(claim.estado)
    if estado_val == ClaimEstadoEnum.atendido.value and reply_in.conforme is False:
        claim.estado = ClaimEstadoEnum.en_proceso
        claim.fecha_atencion = None

    msg = ClaimMessage(
        claim_id=claim.id,
        autor="cliente",
        canal="web",
        texto=reply_in.texto.strip(),
    )
    db.add(msg)
    db.commit()
    db.refresh(claim)

    background_tasks.add_task(
        notify_claim_customer_reply,
        claim,
        reply_in.texto.strip(),
        reply_in.conforme,
    )

    return claim_to_tracking_response(claim)
