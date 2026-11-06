import re
import unicodedata


SYNONYMS = {
    "cuadrada": "cuadrado",
    "cuadradas": "cuadrado",
    "negra": "negro",
    "negras": "negro",
    "negros": "negro",
    "redonda": "redondo",
    "redondas": "redondo",
    "galv": "galvanizado",
    "galvanizada": "galvanizado",
    "galvanizadas": "galvanizado",
    "ang": "angulo",
    "laminada": "laminado",
    "laminadas": "laminado",
    "lac": "lac",
    "laminada en caliente": "lac",
    "laminado en caliente": "lac",
    "laminadas en caliente": "lac",
    "laminados en caliente": "lac",
    "laf": "laf",
    "laminada en frio": "laf",
    "laminado en frio": "laf",
    "laminadas en frio": "laf",
    "laminados en frio": "laf",
    "pulg": "pulgada",
    "pulgadas": "pulgada",
    "in": "pulgada",
}

_SINGULAR_TERMS = frozenset(
    {
        "acero",
        "accesorio",
        "angulo",
        "canal",
        "careta",
        "corrugado",
        "cuadrado",
        "disco",
        "electrodo",
        "fierro",
        "galvanizado",
        "lac",
        "laf",
        "laminado",
        "liso",
        "negro",
        "perfil",
        "plancha",
        "platina",
        "rectangular",
        "redondo",
        "tornillo",
        "tubo",
        "viga",
    }
)
_IGNORED_TERMS = frozenset({"de"})
_TOKEN_PATTERN = re.compile(r"\d+(?:\.\d+)?(?:/\d+)?|[a-z]+")


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _singularize(term: str) -> str:
    if term in _SINGULAR_TERMS:
        return term

    candidates = []
    if term.endswith("ces"):
        candidates.append(term[:-3] + "z")
    if term.endswith("es"):
        candidates.append(term[:-2])
    if term.endswith("s"):
        candidates.append(term[:-1])
    return next(
        (candidate for candidate in candidates if candidate in _SINGULAR_TERMS),
        term,
    )


def normalize_terms(text: str) -> str:
    """Canonicalize catalog terms, common variants, measurements, and whitespace."""
    value = str(text or "").casefold().replace("×", " x ")
    for symbol in ('"', "″", "“", "”"):
        value = value.replace(symbol, " pulgada ")
    value = _strip_accents(value)
    value = re.sub(r"(?<=\d),(?=\d)", ".", value)
    value = re.sub(r"[^a-z0-9./]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    for variant, canonical in sorted(SYNONYMS.items(), key=lambda item: -len(item[0])):
        pattern = rf"\b{re.escape(_strip_accents(variant))}\b"
        value = re.sub(pattern, canonical, value)

    terms = []
    for term in _TOKEN_PATTERN.findall(value):
        if term in _IGNORED_TERMS:
            continue
        terms.append(_singularize(term))
    return " ".join(terms)
