from app.core.security import get_password_hash
from app.db.models import User, UserRolEnum


def seed_admin_user(db_session):
    admin = User(
        email="admin@kenpaku.pe",
        password_hash=get_password_hash("AdminKenpaku2026!"),
        rol=UserRolEnum.admin,
        activo=True,
    )
    db_session.add(admin)
    db_session.commit()
    return admin


def test_login_success(client, db_session):
    seed_admin_user(db_session)
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@kenpaku.pe", "password": "AdminKenpaku2026!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_credentials(client, db_session):
    seed_admin_user(db_session)
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@kenpaku.pe", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "UNAUTHORIZED"
    assert data["detail"] == "Credenciales incorrectas."


def test_admin_endpoint_unauthorized_without_token(client):
    response = client.get("/api/admin/dashboard")
    assert response.status_code == 401
