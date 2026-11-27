from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

BUSINESS_TIMEZONE = timezone(-timedelta(hours=5))

FERIADOS_FIJOS_PE: set[tuple[int, int]] = {
    (1, 1),
    (5, 1),
    (6, 29),
    (7, 28),
    (7, 29),
    (8, 30),
    (10, 8),
    (11, 1),
    (12, 8),
    (12, 25),
}

# Feriados móviles (Semana Santa) y feriados extraordinarios deben agregarse a FERIADOS_EXTRA como fechas completas; verificar cada año
FERIADOS_EXTRA: set[date] = set()


def is_business_day(d: date) -> bool:
    """Verifica si una fecha es día hábil (no sábado, no domingo, no feriado)."""
    if d.weekday() >= 5:
        return False
    if (d.month, d.day) in FERIADOS_FIJOS_PE:
        return False
    if d in FERIADOS_EXTRA:
        return False
    return True


def add_business_days(start: datetime, n: int) -> datetime:
    """
    Convierte start a fecha de Lima (asumiendo UTC si es naive);
    el día de registro NO cuenta; devuelve el final (23:59:59) del
    n-ésimo día hábil siguiente, con tzinfo de Lima.
    """
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    start_lima = start.astimezone(BUSINESS_TIMEZONE)

    current_date = start_lima.date()
    counted = 0
    while counted < n:
        current_date += timedelta(days=1)
        if is_business_day(current_date):
            counted += 1

    return datetime.combine(
        current_date, time(23, 59, 59), tzinfo=BUSINESS_TIMEZONE
    )


def dias_habiles_restantes(
    fecha_limite: datetime, now: Optional[datetime] = None
) -> int:
    """
    Calcula los días hábiles entre hoy (Lima) y la fecha límite.
    Devuelve 0 si vence hoy, positivo si faltan días, o NEGATIVO si ya venció.
    """
    if now is None:
        now = datetime.now(BUSINESS_TIMEZONE)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_lima = now.astimezone(BUSINESS_TIMEZONE)

    if fecha_limite.tzinfo is None:
        fecha_limite = fecha_limite.replace(tzinfo=timezone.utc)
    limite_lima = fecha_limite.astimezone(BUSINESS_TIMEZONE)

    today = now_lima.date()
    limite_date = limite_lima.date()

    if today == limite_date:
        return 0
    elif today < limite_date:
        count = 0
        cur = today + timedelta(days=1)
        while cur <= limite_date:
            if is_business_day(cur):
                count += 1
            cur += timedelta(days=1)
        return count
    else:
        count = 0
        cur = limite_date + timedelta(days=1)
        while cur <= today:
            if is_business_day(cur):
                count += 1
            cur += timedelta(days=1)
        return -count if count > 0 else -1


def claim_fecha_limite(claim: Any) -> datetime:
    """
    Devuelve claim.fecha_limite o, si es None (reclamos antiguos),
    add_business_days(claim.fecha, 15).
    """
    if getattr(claim, "fecha_limite", None) is not None:
        return claim.fecha_limite
    return add_business_days(claim.fecha, 15)
