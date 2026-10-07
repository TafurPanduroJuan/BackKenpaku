from app.services.anonymizer import anonymize_text


def test_anonymize_dni():
    raw = "Mi DNI es 72849102 y me llamo Juan."
    anon = anonymize_text(raw)
    assert "72849102" not in anon
    assert "[DNI]" in anon


def test_anonymize_ruc():
    raw = "Facturar a la empresa RUC 20601234567 por favor."
    anon = anonymize_text(raw)
    assert "20601234567" not in anon
    assert "[RUC]" in anon


def test_anonymize_phone_and_email():
    raw = "Escríbeme a cliente@gmail.com o llámame al 987654321."
    anon = anonymize_text(raw)
    assert "cliente@gmail.com" not in anon
    assert "987654321" not in anon
    assert "[EMAIL]" in anon
    assert "[TEL]" in anon


def test_anonymize_address():
    raw = "Enviar la orden a la Av. Néstor Gambetta 456 Mz. B Lt. 12."
    anon = anonymize_text(raw)
    assert "Av. Néstor Gambetta" not in anon
    assert "[DIRECCION]" in anon
