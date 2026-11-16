from app.services.intent_model import predecir_intencion

CAMPOS = {"intencion_id", "intencion", "probabilidad", "baja_confianza", "accion"}


def test_prediccion_reclamo():
    r = predecir_intencion({"mensaje_texto": "mi pedido llegó con los tubos doblados, quiero que lo cambien",
                            "timestamp": "2026-11-13 02:30:00+00:00"})
    assert set(r) == CAMPOS
    assert r["intencion_id"] == 2


def test_prediccion_compra_y_cotizacion():
    assert predecir_intencion({"mensaje_texto": "quiero comprar 10 planchas LAF 1.5 mm"})["intencion_id"] == 3
    assert predecir_intencion({"mensaje_texto": "cuanto cuesta el tubo cuadrado 40x40"})["intencion_id"] == 1


def test_endpoint_intent(client):
    r = client.post("/api/ml/intent", json={"mensaje_texto": "a que hora atienden los domingos"})
    assert r.status_code == 200
    assert set(r.json()) == CAMPOS


def test_endpoint_rechaza_mensaje_vacio(client):
    assert client.post("/api/ml/intent", json={"mensaje_texto": ""}).status_code == 422
