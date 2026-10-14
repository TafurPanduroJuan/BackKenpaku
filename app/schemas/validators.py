import re

_NOMBRE_RE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ '.\-]*$")
_DOCUMENTO_RE = re.compile(r"^[A-Za-z0-9]{8,12}$")
_CELULAR_RE = re.compile(r"^9\d{8}$")


def validar_nombre(valor: str) -> str:
    limpio = " ".join(valor.split())
    if len(limpio) < 2 or not _NOMBRE_RE.match(limpio):
        raise ValueError(
            "El nombre solo puede contener letras, espacios, puntos, guiones y apóstrofes."
        )
    return limpio


def validar_telefono(valor: str) -> str:
    limpio = re.sub(r"[\s\-()]", "", valor)
    if limpio.startswith("+51"):
        limpio = limpio[3:]
    elif limpio.startswith("51") and len(limpio) == 11:
        limpio = limpio[2:]
    if not _CELULAR_RE.match(limpio):
        raise ValueError(
            "Ingrese un celular peruano válido: 9 dígitos y que empiece con 9."
        )
    return limpio


def validar_documento(valor: str) -> str:
    limpio = valor.strip()
    if not _DOCUMENTO_RE.match(limpio):
        raise ValueError(
            "El documento debe tener entre 8 y 12 caracteres alfanuméricos, sin espacios ni símbolos."
        )
    return limpio.upper()


def limpiar_texto_opcional(valor):
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None