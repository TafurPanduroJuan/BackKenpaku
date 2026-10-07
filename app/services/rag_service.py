import math
import time
import uuid
from typing import List, Tuple
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ChatLog, ChatRolEnum, Product
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.product import ProductResponse, compute_stock_estado
from app.services.anonymizer import anonymize_text
from app.services.embeddings import get_embedding
from app.services.llm_service import generate_llm_reply
from app.services.whatsapp import build_whatsapp_handoff_url


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
    if any(k in lower for k in ["reclamo", "queja", "defectuoso", "mal estado", "soporte"]):
        return 2
    if any(k in lower for k in ["precio", "cuanto", "cuánto", "cotizar", "cotización", "costo", "vale"]):
        return 1
    return 0


def contains_product_keyword(text: str) -> bool:
    """Detecta si el mensaje contiene términos clave de productos de acero."""
    keywords = ["tubo", "plancha", "perfil", "angulo", "ángulo", "fierro", "laf", "lac", "galvanizado", "corrugado"]
    lower = text.lower()
    return any(k in lower for k in keywords)


def process_chat_rag(db: Session, chat_in: ChatRequest) -> ChatResponse:
    """
    Orquesta el flujo completo de RAG:
    1. Generación de embedding de la consulta.
    2. Búsqueda de productos más cercanos con pgvector (distancia coseno).
    3. Si no hay coincidencias bajo el umbral -> Handoff inmediato sin llamar al LLM.
    4. Si hay productos -> Armado de contexto con datos en tiempo real (precio/stock), llamada al LLM con historial.
    5. Anonimización del mensaje de usuario y registro en chat_logs.
    """
    start_time = time.time()

    conversation_id = chat_in.conversation_id or uuid.uuid4()
    raw_message = chat_in.message.strip()

    # 1. Generar embedding de la pregunta
    query_vector = get_embedding(raw_message)

    # 2. Buscar productos activos
    active_products = db.query(Product).filter(Product.activo == True).all()

    # Calcular distancia coseno para cada producto
    scored_products: List[Tuple[Product, float]] = []
    for prod in active_products:
        if prod.embedding and isinstance(prod.embedding, list):
            dist = cosine_distance_python(query_vector, prod.embedding)
        else:
            # Fallback por coincidencia de texto en SQLite / sin embedding
            lower_msg = raw_message.lower()
            if prod.nombre.lower() in lower_msg or prod.categoria.value in lower_msg or (prod.medida and prod.medida.lower() in lower_msg):
                dist = 0.2
            else:
                dist = 0.8
        scored_products.append((prod, dist))

    # Ordenar por menor distancia y filtrar por umbral máximo
    scored_products.sort(key=lambda x: x[1])
    relevant_products = [
        prod for prod, dist in scored_products[:4] if dist <= settings.RAG_MAX_DISTANCE
    ]

    # 3. REGLA: Si no hay productos relevantes -> HANDOFF directo sin llamar al LLM
    if not relevant_products and not chat_in.product_id:
        handoff_url = build_whatsapp_handoff_url(raw_message)
        reply = (
            "No encontré productos en nuestro catálogo de acero que coincidan exactamente con tu consulta. "
            "Te conecto de inmediato con un asesor humano por WhatsApp para brindarte atención personalizada."
        )

        # Anonimizar y guardar log
        anon_msg = anonymize_text(raw_message)
        user_log = ChatLog(
            id_conversacion=conversation_id,
            rol=ChatRolEnum.user,
            mensaje_texto=anon_msg,
            longitud_mensaje=len(raw_message),
            contiene_palabra_clave_producto=contains_product_keyword(raw_message),
            intencion_etiquetada=classify_intention(raw_message),
        )
        assistant_log = ChatLog(
            id_conversacion=conversation_id,
            rol=ChatRolEnum.assistant,
            mensaje_texto=reply,
            longitud_mensaje=len(reply),
            contiene_palabra_clave_producto=False,
            intencion_etiquetada=None,
        )
        db.add_all([user_log, assistant_log])
        db.commit()

        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply,
            products=[],
            handoff=True,
            whatsapp_url=handoff_url,
            generated_by_ai=True,
        )

    # Si se pasó un product_id específico y no estaba en relevantes, añadirlo
    if chat_in.product_id and not any(p.id == chat_in.product_id for p in relevant_products):
        specified = db.query(Product).filter(Product.id == chat_in.product_id, Product.activo == True).first()
        if specified:
            relevant_products.insert(0, specified)

    # 4. Armar contexto en tiempo real con lectura directa de BD
    context_lines = []
    product_responses = []
    for p in relevant_products:
        stock_st = compute_stock_estado(p.stock_disponible)
        context_lines.append(
            f"- {p.nombre} (Categoría: {p.categoria.value}, Acabado: {p.acabado.value if p.acabado else 'N/A'}). "
            f"Medida: {p.medida or 'N/A'}, Espesor: {p.espesor or 'N/A'}. "
            f"Precio: S/ {p.precio_unitario:.2f} (IGV incluido). Stock: {p.stock_disponible} unidades ({stock_st}). "
            f"Ficha técnica: {p.ficha_tecnica or 'N/A'}"
        )
        product_responses.append(
            ProductResponse(
                id=p.id,
                nombre=p.nombre,
                categoria=p.categoria,
                acabado=p.acabado,
                medida=p.medida,
                espesor=p.espesor,
                descripcion_corta=p.descripcion_corta,
                ficha_tecnica=p.ficha_tecnica,
                precio_unitario=p.precio_unitario,
                stock_disponible=p.stock_disponible,
                stock_estado=stock_st,
                imagen_url=p.imagen_url,
            )
        )

    context_text = "\n".join(context_lines)

    # Recuperar historial de los últimos 6 mensajes
    past_logs = (
        db.query(ChatLog)
        .filter(ChatLog.id_conversacion == conversation_id)
        .order_by(ChatLog.timestamp.asc())
        .all()
    )
    history = [(log.rol.value, log.mensaje_texto) for log in past_logs[-6:]]

    # Llamar al LLM con el contexto e historial
    reply_text, handoff, whatsapp_url = generate_llm_reply(
        raw_message, context_text, history
    )

    # 5. Anonimizar y guardar logs
    anon_msg = anonymize_text(raw_message)
    user_log = ChatLog(
        id_conversacion=conversation_id,
        rol=ChatRolEnum.user,
        mensaje_texto=anon_msg,
        longitud_mensaje=len(raw_message),
        contiene_palabra_clave_producto=contains_product_keyword(raw_message),
        intencion_etiquetada=classify_intention(raw_message),
    )
    assistant_log = ChatLog(
        id_conversacion=conversation_id,
        rol=ChatRolEnum.assistant,
        mensaje_texto=reply_text,
        longitud_mensaje=len(reply_text),
        contiene_palabra_clave_producto=bool(product_responses),
        intencion_etiquetada=None,
    )
    db.add_all([user_log, assistant_log])
    db.commit()

    latency_ms = (time.time() - start_time) * 1000
    print(f"⏱️ Chat RAG procesado en {latency_ms:.2f} ms")

    return ChatResponse(
        conversation_id=conversation_id,
        reply=reply_text,
        products=product_responses,
        handoff=handoff,
        whatsapp_url=whatsapp_url,
        generated_by_ai=True,
    )
