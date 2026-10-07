def test_get_categories(client):
    """Verifica que /api/categories retorne la lista de categorías con su conteo."""
    response = client.get("/api/categories")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 5
    # Verificar estructura de categorías
    first_cat = data[0]
    assert "slug" in first_cat
    assert "nombre" in first_cat
    assert "descripcion" in first_cat
    assert "total" in first_cat
