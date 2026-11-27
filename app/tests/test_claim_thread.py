from datetime import date, datetime, timezone
import pytest

from app.db.models import Claim, ClaimEstadoEnum, ClaimMessage, ClaimTipoBienEnum, ClaimTipoEnum
from app.services.business_days import (
    BUSINESS_TIMEZONE,
    add_business_days,
    claim_fecha_limite,
    dias_habiles_restantes,
    is_business_day,
)


def test_add_business_days_15_days():
    # Lunes 2026-03-02 con n=15 debe devolver lunes 2026-03-23 al final del día
    start = datetime(2026, 3, 2, 10, 0, 0, tzinfo=timezone.utc)
    res = add_business_days(start, 15)
    assert res.date() == date(2026, 3, 23)
    assert res.hour == 23 and res.minute == 59 and res.second == 59
    assert res.tzinfo == BUSINESS_TIMEZONE


def test_add_business_days_friday_to_monday():
    # Un registro en viernes con n=1 cae en lunes (salta sábado y domingo)
    # 2026-03-06 es viernes -> 2026-03-09 es lunes
    start = datetime(2026, 3, 6, 14, 30, 0, tzinfo=BUSINESS_TIMEZONE)
    res = add_business_days(start, 1)
    assert res.date() == date(2026, 3, 9)
    assert res.hour == 23 and res.minute == 59 and res.second == 59


def test_add_business_days_skips_holiday():
    # Jueves 2026-04-30 con n=1 devuelve lunes 2026-05-04 (1 de mayo es feriado Día del Trabajo)
    start = datetime(2026, 4, 30, 8, 0, 0, tzinfo=timezone.utc)
    res = add_business_days(start, 1)
    assert res.date() == date(2026, 5, 4)
    assert res.hour == 23 and res.minute == 59 and res.second == 59


def test_dias_habiles_restantes():
    # Mismo día: devuelve 0
    fecha_limite = datetime(2026, 3, 23, 23, 59, 59, tzinfo=BUSINESS_TIMEZONE)
    now_mismo_dia = datetime(2026, 3, 23, 11, 0, 0, tzinfo=BUSINESS_TIMEZONE)
    assert dias_habiles_restantes(fecha_limite, now_mismo_dia) == 0

    # Fecha límite ya pasó: devuelve NEGATIVO
    now_pasado = datetime(2026, 3, 25, 10, 0, 0, tzinfo=BUSINESS_TIMEZONE)
    assert dias_habiles_restantes(fecha_limite, now_pasado) < 0

    # Fecha límite futura: devuelve número positivo de días hábiles
    now_previo = datetime(2026, 3, 20, 10, 0, 0, tzinfo=BUSINESS_TIMEZONE)
    assert dias_habiles_restantes(fecha_limite, now_previo) > 0


def test_claim_fecha_limite_helper():
    # Si tiene fecha_limite explícita la devuelve directamente
    fecha_esperada = datetime(2026, 3, 23, 23, 59, 59, tzinfo=BUSINESS_TIMEZONE)
    claim_con_fecha = Claim(
        fecha=datetime(2026, 3, 2, 10, 0, 0, tzinfo=timezone.utc),
        fecha_limite=fecha_esperada,
    )
    assert claim_fecha_limite(claim_con_fecha) == fecha_esperada

    # Si fecha_limite es None (reclamo legado), calcula add_business_days(claim.fecha, 15)
    claim_antiguo = Claim(
        fecha=datetime(2026, 3, 2, 10, 0, 0, tzinfo=timezone.utc),
        fecha_limite=None,
    )
    calc = claim_fecha_limite(claim_antiguo)
    assert calc.date() == date(2026, 3, 23)
    assert calc.hour == 23 and calc.minute == 59 and calc.second == 59


def test_post_claim_stores_fecha_limite(client, db_session):
    payload = {
        "nombre": "Gaston Acurio",
        "documento": "10456789",
        "telefono": "987654321",
        "correo": "gaston@gmail.com",
        "direccion": "Av. Néstor Gambetta 789, Puente Piedra",
        "tipo_bien": "producto",
        "monto_reclamado": 176.00,
        "descripcion_bien": 'Perfil ángulo 2" x 1/4" x 6 m',
        "tipo": "reclamo",
        "detalle": "El perfil presenta una curvatura pronunciada en el centro que impide su alineación.",
        "pedido_consumidor": "Cambio inmediato del producto por uno en perfecto estado de rectitud.",
        "acepto_terminos": True,
    }

    response = client.post("/api/claims", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "codigo_seguimiento" in data

    claim_db = (
        db_session.query(Claim)
        .filter(Claim.codigo_seguimiento == data["codigo_seguimiento"])
        .first()
    )
    assert claim_db is not None
    assert claim_db.fecha is not None
    assert claim_db.fecha_limite is not None
    assert claim_db.fecha_limite.date() > claim_db.fecha.date()


def test_delete_claim_cascades_messages(db_session):
    claim = Claim(
        codigo_seguimiento="RC-2026-000999",
        nombre="Juan Perez",
        documento="77889900",
        telefono="987654321",
        correo="juan.perez@test.com",
        direccion="Av. Los Pinos 123",
        tipo_bien=ClaimTipoBienEnum.producto,
        descripcion_bien="Tubo LAC 2x2",
        tipo=ClaimTipoEnum.reclamo,
        detalle="Producto con defecto",
        pedido_consumidor="Reposición",
        estado=ClaimEstadoEnum.pendiente,
        fecha=datetime.now(timezone.utc),
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)

    msg1 = ClaimMessage(
        claim_id=claim.id,
        autor="cliente",
        canal="web",
        texto="Adjunto fotos del producto dañado.",
    )
    msg2 = ClaimMessage(
        claim_id=claim.id,
        autor="admin",
        canal="panel",
        texto="Hemos recibido las fotos, procedemos a revisar.",
    )
    db_session.add_all([msg1, msg2])
    db_session.commit()
    db_session.refresh(claim)

    assert len(claim.mensajes) == 2
    msg1_id = msg1.id
    msg2_id = msg2.id

    # Al eliminar el claim, se deben eliminar en cascada sus mensajes asociados
    db_session.delete(claim)
    db_session.commit()

    assert db_session.query(Claim).filter(Claim.id == claim.id).first() is None
    assert (
        db_session.query(ClaimMessage)
        .filter(ClaimMessage.id.in_([msg1_id, msg2_id]))
        .count()
        == 0
    )
