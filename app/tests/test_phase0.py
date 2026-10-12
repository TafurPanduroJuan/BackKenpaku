from decimal import Decimal
import uuid
from starlette.requests import Request

from app.core.rate_limit import get_real_client_ip
from app.core.security import create_access_token, get_password_hash
from app.db.models import Claim, Order, OrderEstadoEnum, OrderItem, Product, ProductCategoryEnum, User, UserRolEnum
from app.routers.claims import generate_claim_code
from app.services.order_service import generate_order_code


def test_get_real_client_ip():
    # 1. Con cabecera X-Forwarded-For múltiple (típico detrás de Render/Cloudflare)
    scope_forwarded = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.195, 10.0.0.1")],
        "client": ("10.0.0.1", 12345),
    }
    req1 = Request(scope_forwarded)
    assert get_real_client_ip(req1) == "203.0.113.195"

    # 2. Con cabecera X-Real-IP
    scope_real = {
        "type": "http",
        "headers": [(b"x-real-ip", b"198.51.100.22")],
        "client": ("10.0.0.1", 12345),
    }
    req2 = Request(scope_real)
    assert get_real_client_ip(req2) == "198.51.100.22"

    # 3. Sin cabeceras proxy (conexión directa)
    scope_direct = {
        "type": "http",
        "headers": [],
        "client": ("192.168.1.50", 12345),
    }
    req3 = Request(scope_direct)
    assert get_real_client_ip(req3) == "192.168.1.50"


def test_generate_codes_uniqueness(db_session):
    # Generar códigos de pedidos consecutivos guardando en sesión
    order_codes = []
    for i in range(5):
        code = generate_order_code(db_session)
        order_codes.append(code)
        order = Order(
            codigo=code,
            cliente_nombre=f"Cliente {i}",
            cliente_telefono="999888777",
            cliente_correo=f"cliente{i}@kenpaku.pe",
            subtotal=Decimal("100.00"),
            igv=Decimal("18.00"),
            total=Decimal("118.00"),
            acepto_privacidad=True,
        )
        db_session.add(order)
        db_session.commit()

    assert len(set(order_codes)) == 5
    assert order_codes == ["KPK-000001", "KPK-000002", "KPK-000003", "KPK-000004", "KPK-000005"]

    # Generar códigos de reclamos consecutivos guardando en sesión
    claim_codes = []
    for i in range(5):
        code = generate_claim_code(db_session)
        claim_codes.append(code)
        claim = Claim(
            codigo_seguimiento=code,
            nombre=f"Reclamante {i}",
            documento="12345678",
            telefono="987654321",
            correo=f"rec{i}@kenpaku.pe",
            direccion="Dirección",
            tipo_bien="producto",
            descripcion_bien="Tubo",
            tipo="reclamo",
            detalle="Detalle",
            pedido_consumidor="Solución",
        )
        db_session.add(claim)
        db_session.commit()

    assert len(set(claim_codes)) == 5
    for code in claim_codes:
        assert code.startswith("RC-")


def test_admin_orders_response_matches_frontend_contract(client, db_session):
    admin = User(
        email="admin_test@kenpaku.pe",
        password_hash=get_password_hash("AdminPass123!"),
        rol=UserRolEnum.admin,
        activo=True,
    )
    db_session.add(admin)
    db_session.commit()

    order = Order(
        codigo="KPK-000099",
        cliente_nombre="Juan Perez",
        cliente_telefono="999888777",
        cliente_correo="juan.perez@test.pe",
        direccion="Av. Túpac Amaru 123",
        recojo_en_tienda=False,
        observaciones="Entregar en garita",
        estado=OrderEstadoEnum.pendiente,
        subtotal=Decimal("100.00"),
        igv=Decimal("18.00"),
        total=Decimal("118.00"),
        acepto_privacidad=True,
    )
    db_session.add(order)
    db_session.commit()

    token = create_access_token(subject=admin.email)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/admin/orders", headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    order_item = next(o for o in data["items"] if o["codigo"] == "KPK-000099")

    # Validar campos que consume Orders.jsx
    assert order_item["cliente_nombre"] == "Juan Perez"
    assert order_item["cliente_telefono"] == "999888777"
    assert order_item["cliente_correo"] == "juan.perez@test.pe"
    assert "created_at" in order_item
    assert order_item["recojo_en_tienda"] is False
    assert Decimal(str(order_item["total"])) == Decimal("118.00")
