from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.rate_limit import allow_quote_code_attempt, check_chat_rate_limit, get_real_client_ip
from app.db.session import get_db
from app.schemas.quote import (
    QuoteAnalysisResponse,
    QuoteItemChoice,
    QuoteRecalculateResponse,
    QuoteRequest,
    QuoteResponse,
)
from app.services import quote_service

router = APIRouter(prefix="/api/quotes", tags=["Proformas"])


def _not_found(request: Request):
    client_ip = get_real_client_ip(request)
    if not allow_quote_code_attempt(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="No encontré esa proforma.",
        )
    raise HTTPException(status_code=404, detail="No encontré esa proforma.")


@router.post(
    "/analyze",
    response_model=QuoteAnalysisResponse,
    dependencies=[Depends(check_chat_rate_limit)],
)
def analyze_quote(
    quote_in: QuoteRequest,
    db: Session = Depends(get_db),
):
    try:
        return quote_service.analyze_quote(db, quote_in)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "",
    response_model=QuoteResponse,
    dependencies=[Depends(check_chat_rate_limit)],
)
def create_quote(
    quote_in: QuoteRequest,
    db: Session = Depends(get_db),
):
    try:
        quote = quote_service.create_quote(db, quote_in)
        return quote_service.to_quote_response(db, quote)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/{codigo}",
    response_model=QuoteResponse,
    dependencies=[Depends(check_chat_rate_limit)],
)
def get_quote(
    codigo: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    quote = quote_service.get_quote_by_code(db, codigo)
    if quote is None:
        _not_found(request)
    return quote_service.to_quote_response(db, quote)


@router.patch(
    "/{codigo}/items/{item_id}",
    response_model=QuoteResponse,
    dependencies=[Depends(check_chat_rate_limit)],
)
def choose_quote_item(
    codigo: str,
    item_id: str,
    choice: QuoteItemChoice,
    request: Request,
    db: Session = Depends(get_db),
):
    quote = quote_service.get_quote_by_code(db, codigo)
    if quote is None:
        _not_found(request)
    if quote_service.quote_is_expired(quote):
        quote.estado = "vencida"
        db.commit()
        raise HTTPException(status_code=409, detail="La proforma venció y no se puede modificar.")
    try:
        quote = quote_service.choose_quote_item(db, quote, UUID(item_id), choice.product_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return quote_service.to_quote_response(db, quote)


@router.post(
    "/{codigo}/recalculate",
    response_model=QuoteRecalculateResponse,
    dependencies=[Depends(check_chat_rate_limit)],
)
def recalculate_quote(
    codigo: str,
    request: Request,
    db: Session = Depends(get_db),
):
    original = quote_service.get_quote_by_code(db, codigo)
    if original is None:
        _not_found(request)
    try:
        new_quote, old_total, comparison = quote_service.recalculate_quote(db, original)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    difference = Decimal(str(new_quote.total)) - Decimal(str(old_total))
    percentage = (
        difference * Decimal("100") / Decimal(str(old_total))
        if Decimal(str(old_total)) != 0
        else None
    )
    return QuoteRecalculateResponse(
        proforma=quote_service.to_quote_response(db, new_quote),
        total_anterior=old_total,
        total_nuevo=new_quote.total,
        diferencia=difference.quantize(Decimal("0.01")),
        diferencia_pct=percentage.quantize(Decimal("0.01")) if percentage is not None else None,
        comparacion=comparison,
    )