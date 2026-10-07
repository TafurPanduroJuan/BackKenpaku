from datetime import datetime, timezone


def test_create_claim_success(client, db_session):
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
    current_year = datetime.now(timezone.utc).year
    assert data["codigo_seguimiento"].startswith(f"RC-{current_year}-")
    assert "fecha" in data


def test_create_claim_without_terms_returns_422(client):
    payload = {
        "nombre": "Maria Lopez",
        "documento": "45678912",
        "telefono": "912345678",
        "correo": "maria@gmail.com",
        "direccion": "Calle Los Olivos 123",
        "tipo_bien": "servicio",
        "descripcion_bien": "Atención en tienda",
        "tipo": "queja",
        "detalle": "Demora excesiva en la atención presencial.",
        "pedido_consumidor": "Mejora en los tiempos de espera.",
        "acepto_terminos": False,  # Términos no aceptados
    }

    response = client.post("/api/claims", json=payload)
    assert response.status_code == 422
