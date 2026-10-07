import re


def anonymize_text(text: str) -> str:
    """
    Anonimiza datos personales sensibles según Ley 29733.
    Reemplaza DNI (8 dígitos), RUC (11 dígitos), teléfonos, correos y direcciones por marcadores.
    """
    if not text:
        return text

    anonymized = text

    # 1. Correos electrónicos
    email_regex = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    anonymized = re.sub(email_regex, "[EMAIL]", anonymized)

    # 2. RUC (11 dígitos comenzando usualmente por 10, 20, 15 o 17)
    ruc_regex = r"\b(10|20|15|17)\d{9}\b"
    anonymized = re.sub(ruc_regex, "[RUC]", anonymized)

    # 3. DNI (8 dígitos exactos)
    dni_regex = r"\b\d{8}\b"
    anonymized = re.sub(dni_regex, "[DNI]", anonymized)

    # 4. Teléfonos móviles de Perú (9 dígitos iniciando con 9, con opcionales guiones/espacios)
    tel_regex = r"\b9\d{2}[-\s]?\d{3}[-\s]?\d{3}\b"
    anonymized = re.sub(tel_regex, "[TEL]", anonymized)

    # 5. Direcciones evidentes (Av., Calle, Jr., Mz., Lt., etc.)
    address_regex = r"\b(Av\.|Avenida|Calle|Jr\.|Jirón|Pasaje|Pj\.|Mz\.|Manzana|Lt\.|Lote)\s+[A-Za-z0-9áéíóúñÁÉÍÓÚÑ\s\.\,]+"
    anonymized = re.sub(address_regex, "[DIRECCION]", anonymized, flags=re.IGNORECASE)

    return anonymized
