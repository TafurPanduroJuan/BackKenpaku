def test_health_check(client):
    """Verifica que el endpoint /api/health devuelva status 200 y {"status": "ok"}."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
