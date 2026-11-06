import math
import re
import unicodedata
import uuid
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.prompts import OFFTOPIC_REJECTION
from app.db.models import ChatLog, ChatRolEnum, Product
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.product import ProductResponse, compute_stock_estado
from app.services.anonymizer import anonymize_text
from app.services.embeddings import get_embedding
from app.services.llm_service import GENERAL_CONTEXT, NO_MATCH_CONTEXT, classify_offtopic, generate_llm_reply
from app.core.rate_limit import allow_quote_code_attempt
from app.services import quote_service


def cosine_distance_python(v1: List[float], v2: List[float]) -> float:
    """Calcula la distancia coseno entre dos vectores numéricos."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 1.0

    dot = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = math.sqrt(sum(a * a for a in v1))
    norm_v2 = math.sqrt(sum(b * b for b in v2))

    if norm_v1 == 0 or norm_v2 == 0:
        return 1.0

    similarity = dot / (norm_v1 * norm_v2)

    return max(0.0, 1.0 - similarity)


def classify_intention(text: str) -> int:
    """
    Etiqueta la intención del mensaje para el contrato de datos posterior de ML:

    0: Consulta general
    1: Cotización / Precio
    2: Reclamo / Soporte
    3: Intención firme de compra
    """
    lower = text.lower()

    if any(k in lower for k in ["comprar", "pedido", "compro", "llevo", "ordenar"]):
        return 3

    if any(
        k in lower
        for k in ["reclamo", "queja", "defectuoso", "mal estado", "soporte"]
    ):
        return 2

    if any(
        k in lower
        for k in [
            "precio",
            "cuanto",
            "cuánto",
            "cotizar",
            "cotización",
            "costo",
            "vale",
        ]
    ):
        return 1

    return 0


def contains_product_keyword(text: str) -> bool:
    """Detecta si el mensaje contiene términos clave de productos de acero."""

    keywords = [
        "tubo",
        "plancha",
        "perfil",
        "angulo",
        "ángulo",
        "fierro",
        "laf",
        "lac",
        "galvanizado",
        "corrugado",
    ]

    lower = text.lower()

    return any(k in lower for k in keywords)


def is_general_query(text: str) -> bool:
    """Detecta saludos y consultas breves sobre los datos de contacto del negocio."""
    normalized = unicodedata.normalize("NFD", text.lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()
    greetings = {
        "hola",
        "buenas",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "saludos",
        "gracias",
        "muchas gracias",
    }
    if normalized in greetings:
        return True

    contact_terms = (
        "whatsapp",
        "telefono",
        "celular",
        "horario",
        "direccion",
        "ubicacion",
        "donde estan",
        "contacto",
    )
    return any(term in normalized for term in contact_terms)


def _is_list_or_proforma_query(text: str) -> bool:
    return bool(
        re.search(
            r"\b(proforma|cotizaci[oó]n)\b|\blista\b.{0,40}\b(materiales|productos|acero|tubos|perfiles|fierros|planchas)\b|\b(c[oó]digo|c[oó]d)\s+(de\s+)?proforma\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _quote_code_from_message(text: str) -> Optional[str]:
    match = re.search(r"\bKP-\d{8}-[A-HJ-NP-Z2-9]{6}\b", text, flags=re.IGNORECASE)
    return match.group(0).upper() if match else None


def _looks_like_material_list(text: str) -> bool:
    material_mentions = re.findall(
        r"\b(?:tubos?|planchas?|perfiles?|fierros?|angulos?|vigas?|barras?)\b",
        text,
        flags=re.IGNORECASE,
    )
    quantities = re.findall(r"\b\d+(?:[.,]\d+)?\s*(?=(?:tubos?|planchas?|perfiles?|fierros?|angulos?|vigas?|barras?))", text, flags=re.IGNORECASE)
    return len(material_mentions) >= 2 or len(quantities) >= 2 or ("\n" in text and bool(quantities))


def _is_quote_request(text: str) -> bool:
    normalized = unicodedata.normalize("NFD", text.lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return bool(re.search(r"\b(proforma|cotizame|cotizar|cotizalo)\b", normalized)) or _looks_like_material_list(text)


def _product_response(product: Product) -> ProductResponse:
    stock_disponible = max(
        0, product.stock_disponible - (product.stock_reservado or 0)
    )
    return ProductResponse(
        id=product.id,
        nombre=product.nombre,
        categoria=product.categoria,
        tipo=product.tipo,
        forma=product.forma,
        acabado=product.acabado,
        medida=product.medida,
        espesor=product.espesor,
        descripcion_corta=product.descripcion_corta,
        ficha_tecnica=product.ficha_tecnica,
        precio_unitario=product.precio_unitario,
        stock_disponible=stock_disponible,
        stock_estado=compute_stock_estado(stock_disponible),
        imagen_url=product.imagen_url,
    )


def _product_context(products: List[Product]) -> str:
    if not products:
        return NO_MATCH_CONTEXT

    lines = []
    for product in products:
        lines.append(
            " | ".join(
                value
                for value in (
                    f"Producto: {product.nombre}",
                    f"Categoría: {product.categoria.value}",
                    f"Acabado: {product.acabado.value}" if product.acabado else "",
                    f"Medida: {product.medida}" if product.medida else "",
                    f"Espesor: {product.espesor}" if product.espesor else "",
                    f"Precio: S/ {product.precio_unitario:.2f}",
                    f"Stock disponible: {max(0, product.stock_disponible - (product.stock_reservado or 0))}",
                    f"Descripción: {product.descripcion_corta}"
                    if product.descripcion_corta
                    else "",
                    f"Ficha técnica: {product.ficha_tecnica}"
                    if product.ficha_tecnica
                    else "",
                )
                if value
            )
        )
    return "\n".join(lines)


def _save_chat_logs(
    db: Session,
    conversation_id: UUID,
    user_message: str,
    assistant_message: str,
    fuera_de_alcance: bool = False,
) -> None:
    safe_message = anonymize_text(user_message)
    has_product_keyword = contains_product_keyword(user_message)
    db.add_all(
        [
            ChatLog(
                id_conversacion=conversation_id,
                rol=ChatRolEnum.user,
                mensaje_texto=safe_message,
                longitud_mensaje=len(safe_message),
                contiene_palabra_clave_producto=has_product_keyword,
                intencion_etiquetada=classify_intention(user_message),
                fuera_de_alcance=fuera_de_alcance,
            ),
            ChatLog(
                id_conversacion=conversation_id,
                rol=ChatRolEnum.assistant,
                mensaje_texto=assistant_message,
                longitud_mensaje=len(assistant_message),
                contiene_palabra_clave_producto=has_product_keyword,
                fuera_de_alcance=fuera_de_alcance,
            ),
        ]
    )
    db.commit()


def _quote_followup_question(missing_fields: List[str]) -> str:
    prompts = {
        "forma": "la forma (cuadrada, rectangular o redonda)",
        "tipo": "el tipo (por ejemplo, ángulo, platina, LAC, LAF o corrugado)",
        "medida": "la medida o diámetro",
        "espesor": "el espesor en milímetros",
        "acabado": "el acabado (negro o galvanizado)",
    }
    details = [prompts[field] for field in missing_fields if field in prompts]
    return (
        "Antes de cotizar, completa tu lista indicando "
        + ", ".join(details)
        + ". Puedes responder con esos datos y los aplicaré a las líneas incompletas."
    )


def _handle_quote_items(db, conversation_id, message, items, client_ip=None):
    analysis = quote_service.analyze_items(db, items)
    missing_fields = list(dict.fromkeys(
        field for line in analysis["items"] for field in line["faltantes"]
    ))
    if missing_fields:
        pending_text = "\n".join(item.texto_original for item in items)
        reply = _quote_followup_question(missing_fields)
        _save_chat_logs(db, conversation_id, message, reply)
        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply,
            products=[],
            handoff=False,
            generated_by_ai=False,
            pending_quote_text=pending_text,
            quote_missing_fields=missing_fields,
        )

    quote = quote_service.create_quote(
        db,
        quote_service.QuoteRequest(items=items, conversation_id=conversation_id),
    )
    reply = quote_service.format_chat_summary(quote)
    _save_chat_logs(db, conversation_id, message, reply)
    return ChatResponse(
        conversation_id=conversation_id,
        reply=reply,
        products=[],
        handoff=False,
        generated_by_ai=False,
        quote=quote_service.quote_summary(quote),
    )


def process_chat_rag(db: Session, chat_in: ChatRequest, client_ip: Optional[str] = None) -> ChatResponse:
    """Busca productos, aplica el filtro de alcance y genera la respuesta del asesor."""
    conversation_id = chat_in.conversation_id or uuid.uuid4()
    message = chat_in.message.strip()

    if chat_in.pending_quote_text:
        try:
            items, analysis = quote_service.complete_pending_items(
                db, chat_in.pending_quote_text, message
            )
        except ValueError as exc:
            reply = str(exc)
            _save_chat_logs(db, conversation_id, message, reply)
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                products=[],
                handoff=False,
                generated_by_ai=False,
                pending_quote_text=chat_in.pending_quote_text,
            )
        missing_fields = list(dict.fromkeys(
            field for line in analysis["items"] for field in line["faltantes"]
        ))
        if missing_fields:
            pending_text = "\n".join(item.texto_original for item in items)
            reply = _quote_followup_question(missing_fields)
            _save_chat_logs(db, conversation_id, message, reply)
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                products=[],
                handoff=False,
                generated_by_ai=False,
                pending_quote_text=pending_text,
                quote_missing_fields=missing_fields,
            )
        try:
            return _handle_quote_items(db, conversation_id, message, items, client_ip)
        except ValueError as exc:
            reply = str(exc)
            _save_chat_logs(db, conversation_id, message, reply)
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                products=[],
                handoff=False,
                generated_by_ai=False,
                pending_quote_text=chat_in.pending_quote_text,
            )

    quote_code = _quote_code_from_message(message)
    if quote_code:
        previous_quote = quote_service.get_quote_by_code(db, quote_code)
        if previous_quote is None:
            if client_ip and not allow_quote_code_attempt(client_ip):
                reply = "No encontré esa proforma."
            else:
                reply = "No encontré esa proforma."
            _save_chat_logs(db, conversation_id, message, reply)
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                products=[],
                handoff=False,
                generated_by_ai=False,
            )
        new_quote, old_total, _comparison = quote_service.recalculate_quote(db, previous_quote)
        summary = quote_service.quote_summary(new_quote)
        difference = Decimal(str(new_quote.total)) - Decimal(str(old_total))
        reply = (
            f"Recalculé la proforma {new_quote.codigo}. El total anterior era S/ {old_total:.2f} "
            f"y el nuevo es S/ {new_quote.total:.2f} (diferencia S/ {difference:.2f})."
        )
        _save_chat_logs(db, conversation_id, message, reply)
        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply,
            products=[],
            handoff=False,
            generated_by_ai=False,
            quote=summary,
        )

    normalized_quote_message = unicodedata.normalize("NFD", message.lower())
    normalized_quote_message = "".join(
        char for char in normalized_quote_message if unicodedata.category(char) != "Mn"
    )
    if re.search(r"\b(recalcular|recalcula|actualizar mi proforma)\b", normalized_quote_message):
        reply = "Envíame el código KP de la proforma que quieres recalcular."
        _save_chat_logs(db, conversation_id, message, reply)
        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply,
            products=[],
            handoff=False,
            generated_by_ai=False,
        )

    if _is_quote_request(message):
        try:
            items = quote_service.parse_list(message)
            return _handle_quote_items(db, conversation_id, message, items, client_ip)
        except ValueError as exc:
            reply = str(exc)
            _save_chat_logs(db, conversation_id, message, reply)
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                products=[],
                handoff=False,
                generated_by_ai=False,
            )

    has_product_keyword = contains_product_keyword(message)
    is_general = is_general_query(message) and not has_product_keyword and not chat_in.product_id
    direct_scope = (
        has_product_keyword
        or is_general
        or chat_in.product_id is not None
        or _is_list_or_proforma_query(message)
    )

    history_rows = (
        db.query(ChatLog)
        .filter(ChatLog.id_conversacion == conversation_id)
        .order_by(ChatLog.timestamp.asc())
        .all()
    )
    chat_history = [(row.rol.value, row.mensaje_texto) for row in history_rows[-6:]]

    if is_general:
        matched_products = []
        nearest_distance = 0.0
    else:
        product_query = db.query(Product).filter(Product.activo.is_(True))
        if chat_in.product_id is not None:
            product_query = product_query.filter(Product.id == chat_in.product_id)
        catalog_products = product_query.all()

        if chat_in.product_id is not None:
            matched_products = catalog_products[:1]
            nearest_distance = 0.0 if matched_products else 1.0
        else:
            query_embedding = get_embedding(message, task_type="RETRIEVAL_QUERY")
            ranked_products = []
            for product in catalog_products:
                if product.embedding is None:
                    continue
                product_embedding = list(product.embedding)
                distance = cosine_distance_python(query_embedding, product_embedding)
                ranked_products.append((distance, product))
            ranked_products.sort(key=lambda item: item[0])
            nearest_distance = ranked_products[0][0] if ranked_products else 1.0
            matched_products = [
                product
                for distance, product in ranked_products[:5]
                if distance <= settings.RAG_MAX_DISTANCE
            ]

    if not direct_scope and nearest_distance > settings.OFFTOPIC_MIN_DISTANCE:
        in_scope = classify_offtopic(message)
        if in_scope is False:
            _save_chat_logs(
                db,
                conversation_id,
                message,
                OFFTOPIC_REJECTION,
                fuera_de_alcance=True,
            )
            return ChatResponse(
                conversation_id=conversation_id,
                reply=OFFTOPIC_REJECTION,
                products=[],
                handoff=False,
                generated_by_ai=False,
            )

    if is_general:
        context_text = GENERAL_CONTEXT
    else:
        context_text = _product_context(matched_products)

    reply, handoff, whatsapp_url = generate_llm_reply(
        message,
        context_text,
        chat_history,
    )
    _save_chat_logs(db, conversation_id, message, reply)

    return ChatResponse(
        conversation_id=conversation_id,
        reply=reply,
        products=[_product_response(product) for product in matched_products],
        handoff=handoff,
        whatsapp_url=whatsapp_url,
        generated_by_ai=True,
    )
