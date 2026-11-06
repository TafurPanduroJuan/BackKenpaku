import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.catalog_vocabulary import normalize_terms
from app.db.models import MeasurementEquivalence, ProductCategoryEnum

INCH_TO_MM = Decimal("25.4")
DEFAULT_TOLERANCE_MM = Decimal("1.5")
DIMENSION_DEFAULTS = (
    ("1/2", Decimal("12"), Decimal("13")),
    ("3/4", Decimal("19"), Decimal("21")),
    ("1", Decimal("24"), Decimal("26")),
    ("1 1/4", Decimal("30"), Decimal("32")),
    ("1 1/2", Decimal("38"), Decimal("40")),
    ("2", Decimal("49"), Decimal("51")),
    ("2 1/2", Decimal("60"), Decimal("64")),
    ("3", Decimal("74"), Decimal("76")),
    ("4", Decimal("99"), Decimal("101")),
)
THICKNESS_DEFAULTS = (
    ("1/16", Decimal("1.4"), Decimal("1.6")),
    ("1/8", Decimal("2.9"), Decimal("3.1")),
    ("3/16", Decimal("4.4"), Decimal("4.6")),
    ("1/4", Decimal("5.9"), Decimal("6.1")),
)

_FRACTION_GLYPHS = {
    "½": " 1/2",
    "⅓": " 1/3",
    "⅔": " 2/3",
    "¼": " 1/4",
    "¾": " 3/4",
    "⅛": " 1/8",
    "⅜": " 3/8",
    "⅝": " 5/8",
    "⅞": " 7/8",
}
_NUMBER = r"(?:\d+/\d+|\d+(?:[.,]\d+)?(?:\s+\d+/\d+)?)"
_NUMBER_RE = re.compile(_NUMBER)


@dataclass(frozen=True)
class ParsedMeasurement:
    values: Tuple[Decimal, ...]
    unit: str
    original: str
    length_m: Optional[Decimal] = None

    @property
    def source_unit(self) -> str:
        return self.unit

    @property
    def original_text(self) -> str:
        return self.original

    @property
    def values_mm(self) -> Tuple[Decimal, ...]:
        multiplier = INCH_TO_MM if self.unit == "inch" else Decimal("1")
        return tuple(value * multiplier for value in self.values)

    @property
    def ancho_mm(self) -> Optional[Decimal]:
        return self.values_mm[0] if self.values_mm else None

    @property
    def alto_mm(self) -> Optional[Decimal]:
        return self.values_mm[1] if len(self.values_mm) > 1 else None

    @property
    def largo_mm(self) -> Optional[Decimal]:
        return self.length_m * Decimal("1000") if self.length_m is not None else None


def _fraction_value(value: str) -> Decimal:
    value = value.strip().replace(",", ".")
    if " " in value:
        whole, fraction = value.split(None, 1)
        numerator, denominator = fraction.split("/", 1)
        return Decimal(whole) + Decimal(numerator) / Decimal(denominator)
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        return Decimal(numerator) / Decimal(denominator)
    return Decimal(value)


def _prepare_measurement(text: str) -> str:
    value = str(text or "").casefold()
    for glyph, fraction in _FRACTION_GLYPHS.items():
        value = value.replace(glyph, fraction)
    value = re.sub(r"(?<=\d)-(?=\d+/\d+)", " ", value)
    value = re.sub(r"(?<=\d)\.(?=\d+/)", " ", value)
    return value.replace("×", "x")


def parse_measurement(text: str) -> Optional[ParsedMeasurement]:
    """Parse dimensions or thickness while retaining source units and original text."""
    original = str(text or "").strip()
    value = _prepare_measurement(original)
    length_match = re.search(r"\bx\s*(\d+(?:[.,]\d+)?)\s*m(?:t|ts|etro|etros)?\b", value)
    length = (
        Decimal(length_match.group(1).replace(",", "."))
        if length_match
        else None
    )
    if length_match:
        value = value[:length_match.start()]

    is_mm = bool(re.search(r"mm\b", value))
    is_inch = bool(
        re.search(r"""(?:["″]|'\s*(?:x|$)|\b(?:pulg(?:ada)?s?|in)\b)""", value)
    )
    numbers = tuple(
        _fraction_value(match.group(0))
        for match in _NUMBER_RE.finditer(value)
    )
    if not numbers:
        return None

    if is_mm:
        unit = "mm"
    elif is_inch or any("/" in match.group(0) for match in _NUMBER_RE.finditer(value)):
        unit = "inch"
    else:
        unit = "inch" if max(numbers) <= Decimal("4") else "mm"
    return ParsedMeasurement(numbers, unit, original, length)


def _read_equivalences(
    db: Optional[Session],
) -> Sequence[MeasurementEquivalence]:
    if db is None:
        return [
            MeasurementEquivalence(
                tipo_medida=kind,
                pulgada=inch,
                mm_minimo=minimum,
                mm_maximo=maximum,
                tolerancia_mm=DEFAULT_TOLERANCE_MM,
            )
            for kind, values in (
                ("dimension", DIMENSION_DEFAULTS),
                ("espesor", THICKNESS_DEFAULTS),
            )
            for inch, minimum, maximum in values
        ]
    rows = db.query(MeasurementEquivalence).all()
    if rows:
        return rows
    defaults = [
        MeasurementEquivalence(
            tipo_medida=kind,
            pulgada=inch,
            mm_minimo=minimum,
            mm_maximo=maximum,
            tolerancia_mm=DEFAULT_TOLERANCE_MM,
        )
        for kind, values in (
            ("dimension", DIMENSION_DEFAULTS),
            ("espesor", THICKNESS_DEFAULTS),
        )
        for inch, minimum, maximum in values
    ]
    db.add_all(defaults)
    db.flush()
    return defaults


def get_measurement_equivalences(db: Session) -> Sequence[MeasurementEquivalence]:
    return _read_equivalences(db)


def _get_equivalence(
    db: Optional[Session],
    kind: str,
    inches: Decimal,
    category: Optional[str],
    equivalences: Optional[Sequence[MeasurementEquivalence]] = None,
) -> Optional[MeasurementEquivalence]:
    candidates = [
        row
        for row in equivalences or _read_equivalences(db)
        if row.tipo_medida == kind
        and _fraction_value(row.pulgada) == inches
        and row.categoria in (category, None)
    ]
    candidates.sort(key=lambda row: row.categoria != category)
    return candidates[0] if candidates else None


def _format_inches(value: Decimal) -> str:
    for label, _, _ in DIMENSION_DEFAULTS + THICKNESS_DEFAULTS:
        if _fraction_value(label) == value:
            return label
    return format(value.normalize(), "f")


def _product_category(category: str) -> str:
    return category.value if isinstance(category, ProductCategoryEnum) else str(category)


def _mm_values(parsed: ParsedMeasurement) -> Tuple[Decimal, ...]:
    return parsed.values_mm


def measurements_match(
    db: Optional[Session],
    requested: str,
    actual: str,
    category: str,
    kind: str = "dimension",
    equivalences: Optional[Sequence[MeasurementEquivalence]] = None,
) -> Tuple[bool, Optional[str], bool]:
    """Return (matches, customer-facing equivalence note, exact physical match)."""
    requested_spec = parse_measurement(requested)
    actual_spec = parse_measurement(actual)
    if not requested_spec or not actual_spec:
        return False, None, False

    requested_values = requested_spec.values
    actual_values = actual_spec.values
    if kind == "dimension" and len(actual_values) > 2:
        actual_values = actual_values[:2]
    if (
        kind == "dimension"
        and len(requested_values) == 1
        and len(actual_values) == 2
        and requested_spec.unit == "inch"
    ):
        requested_values *= 2
    if len(requested_values) != len(actual_values):
        return False, None, False

    requested_mm = _mm_values(ParsedMeasurement(
        requested_values, requested_spec.unit, requested_spec.original
    ))
    actual_mm = _mm_values(ParsedMeasurement(
        actual_values, actual_spec.unit, actual_spec.original
    ))
    if sorted(requested_mm) == sorted(actual_mm):
        return True, None, True

    inch_values = (
        requested_values if requested_spec.unit == "inch"
        else actual_values if actual_spec.unit == "inch"
        else ()
    )
    metric_values = (
        actual_mm if requested_spec.unit == "inch"
        else requested_mm if actual_spec.unit == "inch"
        else ()
    )
    if not inch_values or not metric_values:
        return False, None, False

    category_value = _product_category(category)
    matched_rows = []
    for inch in inch_values:
        row = _get_equivalence(db, kind, inch, category_value, equivalences)
        if row is None:
            return False, None, False
        matched_rows.append(row)
    tolerance = max(
        Decimal(
            str(
                row.tolerancia_mm
                if row.tolerancia_mm is not None
                else DEFAULT_TOLERANCE_MM
            )
        )
        for row in matched_rows
    )
    ranges = sorted(
        (
            Decimal(str(row.mm_minimo)) - tolerance,
            Decimal(str(row.mm_maximo)) + tolerance,
        )
        for row in matched_rows
    )
    unmatched = list(sorted(metric_values))
    for minimum, maximum in ranges:
        index = next(
            (i for i, value in enumerate(unmatched) if minimum <= value <= maximum),
            None,
        )
        if index is None:
            return False, None, False
        unmatched.pop(index)

    if kind == "espesor":
        note = (
            f"Medida equivalente: {_format_inches(inch_values[0])}\" "
            f"= {format(metric_values[0].normalize(), 'f')} mm"
        )
    else:
        note_inches = (
            inch_values[:1]
            if requested_spec.unit == "inch" and len(requested_spec.values) == 1
            else inch_values
        )
        inch_label = " x ".join(f'{_format_inches(value)}"' for value in note_inches)
        mm_label = "x".join(format(value.normalize(), "f") for value in sorted(metric_values))
        note = f"Medida equivalente: {inch_label} = {mm_label} mm"
    return True, note, False


def canonical_measurement(text: str) -> str:
    """Normalize a measurement for display-independent exact comparisons."""
    parsed = parse_measurement(text)
    if not parsed:
        return normalize_terms(text)
    unit = "mm" if parsed.unit == "mm" else "pulgada"
    values = " x ".join(format(value.normalize(), "f") for value in parsed.values)
    return f"{values} {unit}"
