"""Tests para el filtro de mensajes fuera de alcance (Parte 1: Limitar el chat al tema del negocio)."""
from decimal import Decimal
import uuid

from app.core.prompts import OFFTOPIC_REJECTION
from app.db.models import ChatLog, ChatRolEnum, Product, ProductCategoryEnum, ProductAcabadoEnum
from app.services.embeddings import generate_product_embedding_text, get_embedding


def seed_product_for_offtopic_test(db_session):
    """Crea un producto de prueba con embedding para los tests de off-topic."""
    text = generate_product_embedding_text(
        nombre='Tubo negro cuadrado 2" x 2" x 6 m',
        categoria="tubos",
        acabado="negro",
        medida='2" x 2" x 6 m',
        espesor="2 mm",
        ficha_tecnica="Tubo cuadrado de acero negro para estructuras",
    )
    product = Product(
        id=uuid.uuid4(),
        nombre='Tubo negro cuadrado 2" x 2" x 6 m',
        categoria=ProductCategoryEnum.tubos,
        acabado=ProductAcabadoEnum.negro,
        medida='2" x 2" x 6 m',
        espesor="2 mm",
        descripcion_corta="Tubo cuadrado de acero negro",
        ficha_tecnica="Tubo cuadrado de acero negro para estructuras",
        precio_unitario=Decimal("95.00"),
        stock_disponible=20,
        activo=True,
        embedding=get_embedding(text),
    )
    db_session.add(product)
    db_session.commit()
    return product


# ─── Tests de mensajes que deben ser RECHAZADOS (fuera de alcance) ───

class TestOfftopicRejection:
    """Mensajes que no tienen nada que ver con acero/construcción deben dar la respuesta fija de rechazo."""

    def _force_offtopic(self, monkeypatch):
        """Fuerza que el filtro off-topic se active patcheando en rag_service:
        - cosine_distance_python → retorna distancia alta (lejos del catálogo)
        - classify_offtopic → retorna False (fuera de alcance confirmado)
        """
        from app.services import rag_service

        monkeypatch.setattr(
            rag_service, "cosine_distance_python", lambda v1, v2: 0.95
        )
        monkeypatch.setattr(
            rag_service, "classify_offtopic", lambda msg: False
        )

    def test_offtopic_holiday_question(self, client, db_session, monkeypatch):
        """Preguntar por feriados está fuera de alcance."""
        from app.services import rag_service

        seed_product_for_offtopic_test(db_session)
        self._force_offtopic(monkeypatch)
        llm_calls = []

        def track_llm_call(*args):
            llm_calls.append(args)
            return "unexpected main LLM call", False, None

        monkeypatch.setattr(rag_service, "generate_llm_reply", track_llm_call)

        response = client.post("/api/chat", json={"message": "¿Cuándo es el día de la independencia del Perú?"})
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == OFFTOPIC_REJECTION
        assert data["handoff"] is False
        assert data["products"] == []
        assert data["generated_by_ai"] is False

        # Verificar que se guardó como fuera_de_alcance en la BD
        logs = db_session.query(ChatLog).filter(
            ChatLog.id_conversacion == uuid.UUID(data["conversation_id"]),
            ChatLog.fuera_de_alcance == True,
        ).all()
        assert len(logs) == 2  # user + assistant
        assert llm_calls == []

    def test_offtopic_recipe_question(self, client, db_session, monkeypatch):
        """Pedir una receta está fuera de alcance."""
        seed_product_for_offtopic_test(db_session)
        self._force_offtopic(monkeypatch)

        response = client.post("/api/chat", json={"message": "Dame una receta de lomo saltado"})
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == OFFTOPIC_REJECTION
        assert data["handoff"] is False

    def test_offtopic_programming_question(self, client, db_session, monkeypatch):
        """Pedir código de programación está fuera de alcance."""
        seed_product_for_offtopic_test(db_session)
        self._force_offtopic(monkeypatch)

        response = client.post("/api/chat", json={"message": "Escribe un código en Python"})
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == OFFTOPIC_REJECTION
        assert data["handoff"] is False


# ─── Tests de mensajes que deben PASAR (en alcance) ───

class TestInScopeMessages:
    """Mensajes sobre productos, proyectos o datos generales de la empresa deben pasar al flujo normal."""

    def test_inscope_product_keyword(self, client, db_session, monkeypatch):
        """Un mensaje con palabras clave de productos pasa SIN invocar el clasificador."""
        from app.services import rag_service

        seed_product_for_offtopic_test(db_session)

        classify_called = {"count": 0}

        def tracked_classify(msg):
            classify_called["count"] += 1
            return None

        monkeypatch.setattr(rag_service, "classify_offtopic", tracked_classify)

        response = client.post("/api/chat", json={"message": "Precio del tubo cuadrado de 2 pulgadas"})
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] != OFFTOPIC_REJECTION

        # El clasificador off-topic NO debe haberse llamado (el mensaje tiene product keyword)
        assert classify_called["count"] == 0

    def test_inscope_greeting(self, client, db_session, monkeypatch):
        """Un saludo pasa como consulta general sin activar el filtro off-topic."""
        from app.services import rag_service

        seed_product_for_offtopic_test(db_session)

        classify_called = {"count": 0}

        def tracked_classify(msg):
            classify_called["count"] += 1
            return None

        monkeypatch.setattr(rag_service, "classify_offtopic", tracked_classify)

        response = client.post("/api/chat", json={"message": "Hola"})
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] != OFFTOPIC_REJECTION

        # Un saludo coincide con is_general_query, NO llega al clasificador
        assert classify_called["count"] == 0

    def test_inscope_whatsapp_question(self, client, db_session, monkeypatch):
        """Preguntar por el WhatsApp pasa como consulta general."""
        from app.services import rag_service

        seed_product_for_offtopic_test(db_session)

        classify_called = {"count": 0}

        def tracked_classify(msg):
            classify_called["count"] += 1
            return None

        monkeypatch.setattr(rag_service, "classify_offtopic", tracked_classify)

        response = client.post("/api/chat", json={"message": "Cuál es su WhatsApp"})
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] != OFFTOPIC_REJECTION
        assert classify_called["count"] == 0

    def test_inscope_construction_project_passes_when_classifier_says_yes(self, client, db_session, monkeypatch):
        """Un proyecto de construcción que no tiene keywords: si el clasificador dice en_alcance, pasa."""
        from app.services import rag_service

        seed_product_for_offtopic_test(db_session)

        # Distancia alta al catálogo pero el clasificador lo aprueba
        monkeypatch.setattr(rag_service, "cosine_distance_python", lambda v1, v2: 0.95)
        monkeypatch.setattr(rag_service, "classify_offtopic", lambda msg: True)

        response = client.post("/api/chat", json={"message": "¿Qué necesito para un portón de 3 metros?"})
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] != OFFTOPIC_REJECTION

    def test_classifier_skipped_below_configured_distance(self, client, db_session, monkeypatch):
        """Una consulta cercana al catálogo no necesita invocar el clasificador barato."""
        from app.services import rag_service

        seed_product_for_offtopic_test(db_session)
        classify_calls = []
        monkeypatch.setattr(rag_service, "cosine_distance_python", lambda v1, v2: 0.2)
        monkeypatch.setattr(
            rag_service,
            "classify_offtopic",
            lambda message: classify_calls.append(message),
        )

        response = client.post("/api/chat", json={"message": "Necesito una estructura"})

        assert response.status_code == 200
        assert response.json()["reply"] != OFFTOPIC_REJECTION
        assert classify_calls == []


# ─── Tests de seguridad: el clasificador falla → dejar pasar ───

class TestOfftopicClassifierFailure:
    """Si el clasificador LLM falla, el mensaje debe pasar al flujo normal (el prompt protege)."""

    def test_classifier_failure_lets_message_through(self, client, db_session, monkeypatch):
        """Si classify_offtopic retorna None (error), el mensaje pasa al flujo normal."""
        from app.services import rag_service

        seed_product_for_offtopic_test(db_session)

        # Distancia alta + clasificador falla (retorna None)
        monkeypatch.setattr(rag_service, "cosine_distance_python", lambda v1, v2: 0.95)
        monkeypatch.setattr(rag_service, "classify_offtopic", lambda msg: None)

        response = client.post("/api/chat", json={"message": "¿Cuándo es el día de la independencia del Perú?"})
        assert response.status_code == 200
        data = response.json()
        # No debe ser la respuesta fija de rechazo (el clasificador falló → se deja pasar)
        assert data["generated_by_ai"] is True


# ─── Test del filtro en el admin de chat-logs ───

class TestChatLogsOfftopicFilter:
    """El endpoint de chat-logs del admin debe poder filtrar por fuera_de_alcance."""

    def test_filter_fuera_de_alcance(self, client, db_session):
        """Filtrar chat-logs por fuera_de_alcance=true muestra solo conversaciones off-topic."""
        from app.core.security import create_access_token, get_password_hash
        from app.db.models import User, UserRolEnum

        # Crear admin
        admin = User(
            email=f"admin_offtopic_{uuid.uuid4().hex[:6]}@kenpaku.pe",
            password_hash=get_password_hash("AdminKenpaku2026!"),
            rol=UserRolEnum.admin,
            activo=True,
        )
        db_session.add(admin)
        db_session.commit()

        token = create_access_token(subject=admin.email)
        headers = {"Authorization": f"Bearer {token}"}

        # Crear logs normales
        conv_normal = uuid.uuid4()
        db_session.add(ChatLog(
            id_conversacion=conv_normal, rol=ChatRolEnum.user,
            mensaje_texto="Precio del tubo", longitud_mensaje=16,
            contiene_palabra_clave_producto=True, fuera_de_alcance=False,
        ))
        db_session.add(ChatLog(
            id_conversacion=conv_normal, rol=ChatRolEnum.assistant,
            mensaje_texto="El tubo cuesta S/ 95.", longitud_mensaje=22,
            contiene_palabra_clave_producto=True, fuera_de_alcance=False,
        ))

        # Crear logs fuera de alcance
        conv_offtopic = uuid.uuid4()
        db_session.add(ChatLog(
            id_conversacion=conv_offtopic, rol=ChatRolEnum.user,
            mensaje_texto="Dame una receta", longitud_mensaje=15,
            contiene_palabra_clave_producto=False, fuera_de_alcance=True,
        ))
        db_session.add(ChatLog(
            id_conversacion=conv_offtopic, rol=ChatRolEnum.assistant,
            mensaje_texto=OFFTOPIC_REJECTION, longitud_mensaje=len(OFFTOPIC_REJECTION),
            contiene_palabra_clave_producto=False, fuera_de_alcance=True,
        ))
        db_session.commit()

        # Filtrar solo fuera de alcance
        response = client.get("/api/admin/chat-logs?fuera_de_alcance=true", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

        # Todos los items deben pertenecer a conversaciones con fuera_de_alcance
        for item in data["items"]:
            assert item["id_conversacion"] == str(conv_offtopic)

        # Filtrar solo en alcance
        response2 = client.get("/api/admin/chat-logs?fuera_de_alcance=false", headers=headers)
        assert response2.status_code == 200
        data2 = response2.json()
        for item in data2["items"]:
            assert item["id_conversacion"] != str(conv_offtopic)
