from datetime import datetime
from decimal import Decimal
import json
import re
import uuid
import pytest

from app.core.config import settings
from app.core.catalog_vocabulary import normalize_terms
from app.db.models import Product, ProductCategoryEnum, ProductAcabadoEnum
from app.schemas.quote import QuoteLineInput, QuoteRequest
from app.services import quote_service


@pytest.fixture(autouse=True)
def isolate_chat_rate_limit(monkeypatch):
    from app.core import rate_limit

    monkeypatch.setattr(
        rate_limit,
        "chat_rate_limiter",
        rate_limit.IPRateLimiter(requests_per_minute=500, window_seconds=60),
    )


def seed_quote_product(db_session, **overrides):
    values = {
        "id": uuid.uuid4(),
        "nombre": "Tubo cuadrado negro 2x2x1.5mm",
        "categoria": ProductCategoryEnum.tubos,
        "acabado": ProductAcabadoEnum.negro,
        "medida": "2x2",
        "espesor": "1.5mm",
        "precio_unitario": Decimal("118.00"),
        "stock_disponible": 10,
        "stock_reservado": 0,
        "activo": True,
        "embedding": [1.0] + [0.0] * 1535,
    }
    values.update(overrides)
    product = Product(**values)
    db_session.add(product)
    db_session.commit()
    return product


def clear_quote_tables(db_session):
    from app.db.models import Quote, QuoteItem

    db_session.query(QuoteItem).delete()
    db_session.query(Quote).delete()
    db_session.commit()


def test_quote_decimal_totals_stock_and_snapshots(db_session):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session)
    item = QuoteLineInput(texto_original="2 tubos cuadrados 2x2 de 1.5mm", cantidad=Decimal("2"))

    quote = quote_service.create_quote(
        db_session,
        QuoteRequest(items=[item]),
        matcher=lambda _db, _item: {"product": product, "status": "con_precio", "options": []},
    )

    assert quote.total == Decimal("236.00")
    assert quote.subtotal == Decimal("200.00")
    assert quote.igv == Decimal("36.00")
    assert quote.items[0].precio_unitario_snapshot == Decimal("118.00")
    product.precio_unitario = Decimal("150.00")
    db_session.commit()
    db_session.refresh(quote)
    assert quote.items[0].precio_unitario_snapshot == Decimal("118.00")
    assert re.fullmatch(r"KP-\d{8}-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}", quote.codigo)
    assert not set("01IO") & set(quote.codigo.rsplit("-", 1)[-1])


def test_quote_shows_out_of_stock_price_and_ambiguous_without_price(db_session):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session, stock_disponible=0)
    first_option = {
        "product_id": str(product.id),
        "nombre": product.nombre,
        "medida": product.medida,
        "espesor": product.espesor,
        "acabado": "negro",
        "precio_unitario": "118.00",
        "stock_disponible": 0,
    }
    request = QuoteRequest(
        items=[
            QuoteLineInput(texto_original="un tubo", cantidad=Decimal("1")),
            QuoteLineInput(texto_original="un perfil especial", cantidad=Decimal("3")),
        ]
    )
    results = iter(
        [
            {"product": product, "status": "sin_stock", "options": []},
            {"product": None, "status": "ambiguo", "options": [first_option]},
        ]
    )

    quote = quote_service.create_quote(db_session, request, matcher=lambda *_: next(results))

    assert quote.items[0].estado_linea == "sin_stock"
    assert quote.items[0].precio_unitario_snapshot == Decimal("118.00")
    assert quote.items[1].estado_linea == "ambiguo"
    assert quote.items[1].precio_unitario_snapshot is None
    assert quote.total == Decimal("0.00")


def test_quote_end_of_day_is_1159_pm_lima():
    sample = datetime(2026, 11, 4, 10, 30, tzinfo=quote_service.LIMA_TZ)
    valid_until = quote_service._end_of_lima_day(sample)
    assert valid_until.astimezone(quote_service.LIMA_TZ).date() == sample.date()
    assert valid_until.astimezone(quote_service.LIMA_TZ).hour == 23
    assert valid_until.astimezone(quote_service.LIMA_TZ).minute == 59
    assert "11:59 pm (hora de Lima)" in quote_service._quote_notice(
        type("QuoteNotice", (), {"valida_hasta": valid_until, "codigo": "KP-20261104-ABC234"})()
    )


def test_fallback_parser_handles_steel_abbreviations_and_missing_quantity(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    parsed = quote_service.parse_list(
        "10 tubos cuadrados 2x2 de 1.5mm\n5 angulos de 1 1/2\nplancha lac 1/8"
    )

    assert len(parsed) == 3
    assert parsed[0].cantidad == Decimal("10")
    assert "tubos cuadrados" in parsed[0].texto_original
    assert parsed[1].cantidad == Decimal("5")
    assert parsed[2].cantidad == Decimal("1")
    assert parsed[2].cantidad_asumida is True


def test_catalog_vocabulary_normalizes_spanish_variants():
    tube_variants = (
        "tubos cuadrado",
        "tubo cuadrados",
        "TUBO CUADRADA",
        "Tubos Cuadrados",
    )
    assert len({normalize_terms(value) for value in tube_variants}) == 1

    assert normalize_terms("ángulos de 1 1/2") == normalize_terms("angulo 1 1/2")
    assert normalize_terms("planchas LAC") == normalize_terms("plancha lac")
    assert len(
        {
            normalize_terms(value)
            for value in ("galv", "galvanizado", "galvanizados")
        }
    ) == 1
    assert normalize_terms('tubo 2"') == normalize_terms("tubo 2 pulgadas")
    assert normalize_terms('1″') == normalize_terms("1 in")
    assert normalize_terms("1 pulg") == normalize_terms("1 pulgada")
    assert normalize_terms("laminada en caliente") == "lac"
    assert normalize_terms("laminada en frío") == "laf"


def test_extract_attributes_normalizes_client_and_model_terms():
    item = QuoteLineInput(
        texto_original="TUBOS CUADRADA galv 2x2 de 1.5mm",
        cantidad=Decimal("1"),
    )

    attributes = quote_service.extract_attributes(item)

    assert attributes["categoria"] == "tubos"
    assert attributes["forma"] == "cuadrado"
    assert attributes["acabado"] == "galvanizado"
    assert attributes["medida"] == "2 x 2"
    assert attributes["espesor"] == "1.5 mm"


def test_match_item_uses_canonical_product_fields(db_session):
    clear_quote_tables(db_session)
    product = seed_quote_product(
        db_session,
        nombre="Tubo CUADRADA galvanizados 2x2 de 1.5mm",
        tipo="galv",
        forma=None,
        acabado=ProductAcabadoEnum.galvanizado,
        medida="2×2",
        espesor="1,5 MM",
    )

    result = quote_service.match_item(
        db_session,
        QuoteLineInput(
            texto_original="1 tubo cuadrados galvanizados 2x2 de 1.5mm",
            cantidad=Decimal("1"),
        ),
    )

    assert result["product"].id == product.id
    assert result["status"] == "con_precio"
    assert not quote_service._matches_attribute("forma", "cuadrado", Product(
        nombre="Tubo rectangular",
        categoria=ProductCategoryEnum.tubos,
        forma="rectangular",
    ))


def test_gemini_parser_extracts_validated_product_attributes(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    response_payload = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": json.dumps({
                        "items": [{
                            "texto_original": "2 tubos acero",
                            "cantidad": 2,
                            "unidad": "unidad",
                            "descripcion_normalizada": "tubos acero",
                            "atributos": {
                                "categoria": "tubos",
                                "tipo": None,
                                "forma": "cuadrado",
                                "medida": "40x40",
                                "espesor": "1.5mm",
                                "acabado": "negro",
                            },
                        }]
                    }),
                }]
            }
        }]
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return response_payload

    monkeypatch.setattr(
        quote_service.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(),
    )

    parsed = quote_service.parse_list("2 tubos acero")
    attributes = quote_service.extract_attributes(parsed[0])

    assert parsed[0].atributos.categoria == "tubos"
    assert attributes["forma"] == "cuadrado"
    assert attributes["medida"] == "40 x 40"
    assert attributes["espesor"] == "1.5 mm"
    assert attributes["faltantes"] == []


def test_quote_builder_product_id_matches_selected_active_accessory(db_session):
    clear_quote_tables(db_session)
    selected = seed_quote_product(
        db_session,
        nombre="Careta de soldar",
        categoria=ProductCategoryEnum.accesorios,
    )
    seed_quote_product(
        db_session,
        nombre="Disco de corte",
        categoria=ProductCategoryEnum.accesorios,
    )
    item = QuoteLineInput(
        texto_original="1 Careta de soldar",
        cantidad=Decimal("1"),
        product_id=selected.id,
    )

    result = quote_service.match_item(db_session, item)

    assert result["product"].id == selected.id
    assert result["status"] == "con_precio"


def test_unclassified_item_does_not_match_an_arbitrary_product(db_session):
    clear_quote_tables(db_session)
    seed_quote_product(db_session)

    result = quote_service.match_item(
        db_session,
        QuoteLineInput(texto_original="material especial", cantidad=Decimal("1")),
    )

    assert result["status"] == "no_se_vende"
    assert result["product"] is None
    assert result["options"] == []


def test_parser_rejects_more_than_fifty_items(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    source = "\n".join(f"{index} tubos cuadrados" for index in range(1, 52))
    with pytest.raises(ValueError, match="50 ítems"):
        quote_service.parse_list(source)


def test_recalculate_creates_child_quote_and_keeps_parent_snapshot(db_session):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session)
    request = QuoteRequest(items=[QuoteLineInput(texto_original="tubo", cantidad=Decimal("2"))])
    original = quote_service.create_quote(
        db_session,
        request,
        matcher=lambda *_: {"product": product, "status": "con_precio", "options": []},
    )
    original_code = original.codigo
    original_total = original.total
    product.precio_unitario = Decimal("141.60")
    db_session.commit()

    new_quote, old_total, comparison = quote_service.recalculate_quote(db_session, original)

    db_session.refresh(original)
    assert new_quote.codigo != original_code
    assert new_quote.parent_codigo == original_code
    assert old_total == Decimal("236.00")
    assert new_quote.total == Decimal("283.20")
    assert original.total == original_total
    assert original.items[0].precio_unitario_snapshot == Decimal("118.00")
    assert comparison[0].diferencia == Decimal("23.60")


def test_recalculate_marks_inactive_product_unavailable(db_session):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session)
    original = quote_service.create_quote(
        db_session,
        QuoteRequest(items=[QuoteLineInput(texto_original="tubo", cantidad=Decimal("1"))]),
        matcher=lambda *_: {"product": product, "status": "con_precio", "options": []},
    )
    product.activo = False
    db_session.commit()

    new_quote, _old_total, comparison = quote_service.recalculate_quote(db_session, original)

    assert new_quote.items[0].estado_linea == "no_se_vende"
    assert new_quote.items[0].precio_unitario_snapshot is None
    assert new_quote.items[0].nombre_snapshot.startswith("Ya no disponible")
    assert comparison[0].estado == "ya_no_disponible"


def test_recalculate_price_decrease_is_reported(db_session):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session, precio_unitario=Decimal("141.60"))
    original = quote_service.create_quote(
        db_session,
        QuoteRequest(items=[QuoteLineInput(texto_original="tubo", cantidad=Decimal("1"))]),
        matcher=lambda *_: {"product": product, "status": "con_precio", "options": []},
    )
    product.precio_unitario = Decimal("118.00")
    db_session.commit()

    new_quote, old_total, comparison = quote_service.recalculate_quote(db_session, original)

    assert old_total == Decimal("141.60")
    assert new_quote.total == Decimal("118.00")
    assert comparison[0].diferencia == Decimal("-23.60")


def test_expired_quote_is_returned_marked_vencida(db_session):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session)
    quote = quote_service.create_quote(
        db_session,
        QuoteRequest(items=[QuoteLineInput(texto_original="tubo", cantidad=Decimal("1"))]),
        matcher=lambda *_: {"product": product, "status": "con_precio", "options": []},
    )
    quote.valida_hasta = datetime(2026, 11, 3, 23, 59, tzinfo=quote_service.LIMA_TZ)
    db_session.commit()

    response = quote_service.to_quote_response(db_session, quote)

    assert response.estado == "vencida"


def test_quote_http_endpoints_and_generic_missing_code(client, db_session, monkeypatch):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session)
    from app.services import quote_service as quote_module
    from app.services import rag_service
    from app.routers import quotes as quote_router

    monkeypatch.setattr(quote_module, "get_embedding", lambda *args, **kwargs: [1.0] + [0.0] * 1535)
    monkeypatch.setattr(rag_service, "cosine_distance_python", lambda _v1, _v2: 0.1)
    monkeypatch.setattr(quote_router, "allow_quote_code_attempt", lambda _ip: True)
    response = client.post(
        "/api/quotes",
        json={"items": [{"texto_original": "2 tubos cuadrados 2x2 de 1.5mm negro", "cantidad": 2}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == "236.00"
    assert data["items"][0]["estado_linea"] == "con_precio"

    fetched = client.get(f"/api/quotes/{data['codigo']}")
    assert fetched.status_code == 200
    assert fetched.json()["codigo"] == data["codigo"]
    assert fetched.headers["cache-control"] == "no-store"

    missing = client.get("/api/quotes/not-a-real-code")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "No encontré esa proforma."


def test_quote_analyze_reports_missing_fields_without_persisting(client, db_session, monkeypatch):
    clear_quote_tables(db_session)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")

    response = client.post("/api/quotes/analyze", json={"texto": "5 tubos de 2 pulgadas"})

    assert response.status_code == 200
    assert response.json()["items"][0]["faltantes"] == ["forma", "espesor", "acabado"]
    from app.db.models import Quote
    assert db_session.query(Quote).count() == 0


def test_chat_asks_for_missing_quote_data_then_creates_quote(client, db_session, monkeypatch):
    clear_quote_tables(db_session)
    seed_quote_product(db_session)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")

    first = client.post("/api/chat", json={"message": "cotizame 5 tubos de 2 pulgadas"})
    assert first.status_code == 200
    assert first.json()["quote"] is None
    assert first.json()["pending_quote_text"]
    assert "forma" in first.json()["reply"].lower()

    second = client.post("/api/chat", json={
        "message": "cuadrado negro 1.5mm",
        "pending_quote_text": first.json()["pending_quote_text"],
    })
    assert second.status_code == 200
    assert second.json()["quote"]["codigo"].startswith("KP-")
    assert second.json()["pending_quote_text"] is None


def test_failed_quote_lookups_are_rate_limited_by_ip(client, monkeypatch):
    from app.core.rate_limit import IPRateLimiter
    from app.routers import quotes as quote_router

    limiter = IPRateLimiter(requests_per_minute=2, window_seconds=300)
    monkeypatch.setattr(quote_router, "allow_quote_code_attempt", limiter.is_allowed)
    first = client.get("/api/quotes/KP-20261104-AAAAAA")
    second = client.get("/api/quotes/KP-20261104-BBBBBB")
    third = client.get("/api/quotes/KP-20261104-CCCCCC")

    assert first.status_code == 404
    assert second.status_code == 404
    assert third.status_code == 429
    assert third.json()["detail"] == "No encontré esa proforma."


def test_ambiguous_line_can_be_resolved_over_http(client, db_session, monkeypatch):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session)
    from app.services import quote_service as quote_module
    from app.routers import quotes as quote_router

    option = {
        "product_id": str(product.id),
        "nombre": product.nombre,
        "medida": product.medida,
        "espesor": product.espesor,
        "acabado": "negro",
        "precio_unitario": "118.00",
        "stock_disponible": 10,
    }
    quote = quote_module.create_quote(
        db_session,
        QuoteRequest(items=[QuoteLineInput(texto_original="tubo cuadrado", cantidad=Decimal("2"))]),
        matcher=lambda *_: {"product": None, "status": "ambiguo", "options": [option]},
    )
    monkeypatch.setattr(quote_router, "allow_quote_code_attempt", lambda _ip: True)

    response = client.patch(
        f"/api/quotes/{quote.codigo}/items/{quote.items[0].id}",
        json={"product_id": str(product.id)},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["estado_linea"] == "con_precio"
    assert response.json()["total"] == "236.00"


def test_ambiguous_selection_uses_price_snapshot_not_changed_catalog_price(db_session):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session)
    option = quote_service._candidate(product)
    quote = quote_service.create_quote(
        db_session,
        QuoteRequest(items=[QuoteLineInput(texto_original="tubo cuadrado", cantidad=Decimal("2"))]),
        matcher=lambda *_: {"product": None, "status": "ambiguo", "options": [option]},
    )
    product.precio_unitario = Decimal("200.00")
    db_session.commit()

    quote_service.choose_quote_item(db_session, quote, quote.items[0].id, product.id)

    assert quote.items[0].precio_unitario_snapshot == Decimal("118.00")
    assert quote.total == Decimal("236.00")


def test_chat_creates_quote_without_calling_main_llm(client, db_session, monkeypatch):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session)
    from app.services import quote_service as quote_module
    from app.services import rag_service

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(quote_module, "get_embedding", lambda *args, **kwargs: [1.0] + [0.0] * 1535)
    monkeypatch.setattr(rag_service, "cosine_distance_python", lambda _v1, _v2: 0.1)
    monkeypatch.setattr(
        rag_service,
        "generate_llm_reply",
        lambda *_args: (_ for _ in ()).throw(AssertionError("The main LLM must not calculate quote prices")),
    )

    response = client.post(
        "/api/chat",
        json={"message": "10 tubos cuadrados 2x2 de 1.5mm negro\n2 tubos cuadrados 2x2 de 1.5mm negro"},
    )

    assert response.status_code == 200
    assert response.json()["quote"]["codigo"].startswith("KP-")
    assert "Total:" in response.json()["reply"]
    assert "proforma" in response.json()["reply"].lower()


def test_chat_recalculates_known_code_and_hides_unknown_code(client, db_session, monkeypatch):
    clear_quote_tables(db_session)
    product = seed_quote_product(db_session)
    from app.services import quote_service as quote_module
    from app.services import rag_service

    monkeypatch.setattr(quote_module, "get_embedding", lambda *args, **kwargs: [1.0] + [0.0] * 1535)
    monkeypatch.setattr(rag_service, "cosine_distance_python", lambda _v1, _v2: 0.1)
    monkeypatch.setattr(rag_service, "generate_llm_reply", lambda *_: ("unused", False, None))
    original = quote_module.create_quote(
        db_session,
        QuoteRequest(items=[QuoteLineInput(texto_original="tubo", cantidad=Decimal("1"))]),
        matcher=lambda *_: {"product": product, "status": "con_precio", "options": []},
    )
    product.precio_unitario = Decimal("141.60")
    db_session.commit()

    recalculated = client.post("/api/chat", json={"message": f"recalcular {original.codigo}"})
    assert recalculated.status_code == 200
    assert recalculated.json()["quote"]["codigo"] != original.codigo
    assert "total anterior" in recalculated.json()["reply"].lower()

    unknown = client.post("/api/chat", json={"message": "mi codigo es KP-20261104-ZZZZZZ"})
    assert unknown.status_code == 200
    assert unknown.json()["reply"] == "No encontré esa proforma."


def test_chat_requests_quote_code_when_user_only_says_recalculate(client, monkeypatch):
    from app.services import rag_service

    monkeypatch.setattr(
        rag_service,
        "generate_llm_reply",
        lambda *_args: (_ for _ in ()).throw(AssertionError("No debe llamar al LLM principal")),
    )

    response = client.post("/api/chat", json={"message": "Quiero recalcular"})

    assert response.status_code == 200
    assert response.json()["reply"] == "Envíame el código KP de la proforma que quieres recalcular."