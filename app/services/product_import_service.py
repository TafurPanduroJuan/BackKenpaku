import csv
import io
import logging
import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.core.product_rules import infer_product_fields, validate_product_fields
from app.db.models import (
    Product,
    ProductAcabadoEnum,
    ProductCategoryEnum,
    ProductImportHistory,
)
from app.services.embeddings import generate_product_embedding
from app.services.pricing_service import (
    calculate_price_in_pen,
    get_category_margins,
    get_latest_exchange_rate,
    get_pricing_settings,
)

logger = logging.getLogger(__name__)
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 2000
IMPORT_FIELDS = ("sku", "nombre", "precio_usd", "categoria", "tipo", "forma", "acabado", "medida", "espesor", "stock", "imagen_url")
REQUIRED_FIELDS = ("nombre", "precio_usd")
IMPORT_BATCH_SIZE = 20


def _plain_text(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"<[^>]*>", " ", text)
    text = "".join(char for char in text if char.isprintable())
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _parse_rows(data: bytes, filename: str, pasted_text: Optional[str]) -> Tuple[List[dict], List[list]]:
    if pasted_text is not None:
        content = pasted_text.encode("utf-8")
        if len(content) > MAX_IMPORT_BYTES:
            raise ValueError("El texto pegado supera el limite de 5 MB.")
        text = pasted_text.lstrip("\ufeff")
        workbook_rows = _parse_delimited_text(text)
    else:
        if len(data) > MAX_IMPORT_BYTES:
            raise ValueError("El archivo supera el limite de 5 MB.")
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if suffix == "xlsx":
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            sheet = workbook.active
            workbook_rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            workbook.close()
        elif suffix == "csv":
            workbook_rows = _parse_delimited_text(data.decode("utf-8-sig"))
        else:
            raise ValueError("Formato no permitido. Usa .xlsx, .csv o pega una tabla delimitada por tabuladores.")

    nonempty_rows = [row for row in workbook_rows if any(_plain_text(cell) for cell in row)]
    if len(nonempty_rows) < 2:
        raise ValueError("La lista debe incluir encabezados y al menos una fila de productos.")
    if len(nonempty_rows) - 1 > MAX_IMPORT_ROWS:
        raise ValueError(f"La lista supera el maximo de {MAX_IMPORT_ROWS} filas.")

    raw_headers = nonempty_rows[0]
    headers = []
    for index, value in enumerate(raw_headers):
        label = _plain_text(value, 120) or f"Columna {index + 1}"
        headers.append({"key": str(index), "label": label})
    rows = [list(row) for row in nonempty_rows[1:]]
    return headers, rows


def _parse_delimited_text(text: str) -> List[list]:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,;|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in sample else ";" if ";" in sample else ","
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def suggest_mapping(headers: Sequence[dict]) -> Dict[str, str]:
    aliases = {
        "sku": ("sku", "codigo", "codigo proveedor", "cod", "item", "id proveedor", "item code"),
        "nombre": ("nombre", "descripcion", "description", "producto", "articulo", "item descripcion", "product name"),
        "precio_usd": ("precio usd", "price usd", "usd price", "costo usd", "precio", "price", "costo", "valor usd"),
        "categoria": ("categoria", "category", "familia", "linea"),
        "tipo": ("tipo", "type", "subcategoria", "subcategoria"),
        "forma": ("forma", "shape", "perfil"),
        "acabado": ("acabado", "finish", "terminacion"),
        "medida": ("medida", "medidas", "dimension", "dimensiones", "size"),
        "espesor": ("espesor", "grosor", "thickness"),
        "stock": ("stock", "existencia", "inventario", "cantidad", "qty"),
        "imagen_url": ("url imagen", "imagen url", "imagen", "url foto", "foto", "image", "image url"),
    }
    mapped: Dict[str, str] = {}
    used = set()
    normalized_headers = [(item["key"], _normalize(item["label"])) for item in headers]
    for field in IMPORT_FIELDS:
        for alias in aliases[field]:
            alias_normalized = _normalize(alias)
            match = next(
                (key for key, header in normalized_headers if key not in used and header == alias_normalized),
                None,
            )
            if match is not None:
                mapped[field] = match
                used.add(match)
                break
    return mapped


def _parse_decimal(value: str) -> Optional[Decimal]:
    text = re.sub(r"[^0-9,.-]", "", value.strip())
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _category(value: str) -> Optional[ProductCategoryEnum]:
    normalized = _normalize(value)
    aliases = {
        "tubo": ProductCategoryEnum.tubos,
        "tubos": ProductCategoryEnum.tubos,
        "tube": ProductCategoryEnum.tubos,
        "tubes": ProductCategoryEnum.tubos,
        "plancha": ProductCategoryEnum.planchas,
        "planchas": ProductCategoryEnum.planchas,
        "lamina": ProductCategoryEnum.planchas,
        "laminas": ProductCategoryEnum.planchas,
        "sheet": ProductCategoryEnum.planchas,
        "sheets": ProductCategoryEnum.planchas,
        "perfil": ProductCategoryEnum.perfiles,
        "perfiles": ProductCategoryEnum.perfiles,
        "profile": ProductCategoryEnum.perfiles,
        "profiles": ProductCategoryEnum.perfiles,
        "fierro": ProductCategoryEnum.fierros,
        "fierros": ProductCategoryEnum.fierros,
        "barra": ProductCategoryEnum.fierros,
        "barras": ProductCategoryEnum.fierros,
        "varilla": ProductCategoryEnum.fierros,
        "corrugado": ProductCategoryEnum.fierros,
        "accesorio": ProductCategoryEnum.accesorios,
        "accesorios": ProductCategoryEnum.accesorios,
        "accessory": ProductCategoryEnum.accesorios,
        "accessories": ProductCategoryEnum.accesorios,
    }
    return aliases.get(normalized)


def _infer_from_name(name: str) -> dict:
    normalized = _normalize(name)
    inferred: Dict[str, Any] = {}
    category_patterns = (
        (r"\b(tubos?|tubular)\b", ProductCategoryEnum.tubos),
        (r"\b(planchas?|laminas?)\b", ProductCategoryEnum.planchas),
        (r"\b(perfiles?|angulos?|canales?|vigas?)\b", ProductCategoryEnum.perfiles),
        (r"\b(fierros?|barras?|varillas?|corrugados?)\b", ProductCategoryEnum.fierros),
        (r"\b(accesorios?|tornillos?|electrodos?|discos?)\b", ProductCategoryEnum.accesorios),
    )
    for pattern, category in category_patterns:
        if re.search(pattern, normalized):
            inferred["categoria"] = category
            break

    for shape in ("cuadrado", "rectangular", "redondo"):
        if re.search(rf"\b{shape}\b", normalized):
            inferred["forma"] = shape
            break
    category = inferred.get("categoria")
    for product_type in ("corrugado", "liso", "lac", "laf", "galvanizada", "angulo", "platina", "canal"):
        if re.search(rf"\b{product_type}\b", normalized):
            inferred["tipo"] = product_type
            break

    if re.search(r"\b(negro|black)\b", normalized):
        inferred["acabado"] = ProductAcabadoEnum.negro
    elif re.search(r"\b(galvanizado|galvanizada|galv)\b", normalized):
        inferred["acabado"] = ProductAcabadoEnum.galvanizado

    dimensions = re.search(
        r"\d+(?:[.,]\d+)?\s*(?:x|×)\s*\d+(?:[.,]\d+)?(?:\s*(?:x|×)\s*\d+(?:[.,]\d+)?)?(?:\s*(?:mm|cm|m|\"))?",
        name,
        flags=re.IGNORECASE,
    )
    if dimensions:
        measure = re.sub(r"\s+", "", dimensions.group()).replace("×", "x")
        pieces = re.split(r"x", measure, flags=re.IGNORECASE)
        thickness = re.search(r"(\d+(?:[.,]\d+)?)\s*mm\b", measure, flags=re.IGNORECASE)
        if len(pieces) >= 3 and thickness:
            inferred["medida"] = "x".join(pieces[:-1])
            inferred["espesor"] = f"{thickness.group(1)} mm"
        else:
            inferred["medida"] = measure
    if "espesor" not in inferred and re.search(r"\d+(?:[.,]\d+)?\s*mm\b", name, flags=re.IGNORECASE):
        thickness = re.search(r"\d+(?:[.,]\d+)?\s*mm\b", name, flags=re.IGNORECASE)
        inferred["espesor"] = re.sub(r"\s+", " ", thickness.group())
    return inferred


def _normalize_match_text(value: Optional[str]) -> str:
    return _normalize(value or "")


def _match_product(
    row: dict,
    products_by_sku: Dict[str, Product],
    products_by_description: Dict[tuple, Product],
) -> Optional[Product]:
    sku = _normalize_match_text(row.get("sku")).replace(" ", "")
    if sku and sku in products_by_sku:
        return products_by_sku[sku]
    key = (
        _normalize_match_text(row.get("nombre")),
        _normalize_match_text(row.get("medida")),
        _normalize_match_text(row.get("espesor")),
    )
    return products_by_description.get(key) if key[0] else None


def build_preview(
    db: Session,
    data: bytes = b"",
    filename: str = "paste.tsv",
    pasted_text: Optional[str] = None,
    mapping: Optional[dict] = None,
    category_overrides: Optional[dict] = None,
    update_mode: str = "todo",
) -> dict:
    headers, source_rows = _parse_rows(data, filename, pasted_text)
    suggested = suggest_mapping(headers)
    valid_header_keys = {item["key"] for item in headers}
    selected_mapping = suggested if mapping is None else {
        field: str(header_key)
        for field, header_key in mapping.items()
        if field in IMPORT_FIELDS and str(header_key) in valid_header_keys
    }
    overrides = {str(key): str(value) for key, value in (category_overrides or {}).items()}
    product_rows = db.query(Product).all()
    products_by_sku = {
        _normalize_match_text(product.sku).replace(" ", ""): product
        for product in product_rows
        if product.sku
    }
    products_by_description = {
        (
            _normalize_match_text(product.nombre),
            _normalize_match_text(product.medida),
            _normalize_match_text(product.espesor),
        ): product
        for product in product_rows
    }
    pricing = get_pricing_settings(db)
    margins = get_category_margins(db)
    exchange = get_latest_exchange_rate(db)
    exchange_rate = Decimal(str(exchange.valor_venta)) if exchange else None
    claimed_headers = [selected_mapping[field] for field in selected_mapping]
    duplicate_mapping = len(claimed_headers) != len(set(claimed_headers))

    preview_rows = []
    seen_keys = set()
    for line_number, cells in enumerate(source_rows, start=2):
        raw: Dict[str, str] = {}
        for field in IMPORT_FIELDS:
            header_key = selected_mapping.get(field)
            if header_key is None:
                continue
            index = int(header_key)
            raw[field] = _plain_text(cells[index] if index < len(cells) else "", 500)

        errors: List[str] = []
        if duplicate_mapping:
            errors.append("Hay columnas asignadas a mas de un campo.")

        name = _plain_text(raw.get("nombre", ""), 150)
        if not name:
            errors.append("Nombre vacio o columna nombre sin asignar.")

        price_usd = _parse_decimal(raw.get("precio_usd", ""))
        if price_usd is None or price_usd <= 0:
            errors.append("Precio USD invalido.")

        sku = _plain_text(raw.get("sku", ""), 100).upper() or None
        provided_fields = {field for field, value in raw.items() if value != ""}
        inferred_fields = set()

        inferred = _infer_from_name(name) if name else {}
        row_values: Dict[str, Any] = {
            "sku": sku,
            "nombre": name,
            "precio_usd": price_usd,
            "stock": None,
        }

        category_raw = raw.get("categoria", "")
        category = _category(category_raw) if category_raw else inferred.get("categoria")
        if category_raw and category is None:
            errors.append(f"Categoria desconocida: {category_raw}.")
        elif not category_raw and category is not None:
            provided_fields.add("categoria")
            inferred_fields.add("categoria")
        if str(line_number) in overrides:
            category = _category(overrides[str(line_number)])
            provided_fields.add("categoria")
            if category is None:
                errors.append("Categoria asignada manualmente no valida.")
        row_values["categoria"] = category
        for field in ("tipo", "forma"):
            value = _plain_text(raw.get(field, ""), 100 if field == "tipo" else 50)
            if value:
                row_values[field] = value
            else:
                row_values[field] = inferred.get(field)
                if row_values[field] is not None:
                    provided_fields.add(field)
                    inferred_fields.add(field)

        finish_raw = raw.get("acabado", "")
        finish_norm = _normalize(finish_raw)
        finish = None
        if finish_raw:
            finish_aliases = {
                "negro": ProductAcabadoEnum.negro,
                "black": ProductAcabadoEnum.negro,
                "galvanizado": ProductAcabadoEnum.galvanizado,
                "galvanizada": ProductAcabadoEnum.galvanizado,
                "galv": ProductAcabadoEnum.galvanizado,
                "ninguno": ProductAcabadoEnum.ninguno,
                "sin acabado": ProductAcabadoEnum.ninguno,
            }
            finish = finish_aliases.get(finish_norm)
            if finish is None:
                errors.append(f"Acabado desconocido: {finish_raw}.")
        else:
            finish = inferred.get("acabado")
            if finish is not None:
                provided_fields.add("acabado")
                inferred_fields.add("acabado")
        row_values["acabado"] = finish

        for field in ("medida", "espesor"):
            value = _plain_text(raw.get(field, ""), 100)
            if value:
                row_values[field] = value
            else:
                row_values[field] = inferred.get(field)
                if row_values[field] is not None:
                    provided_fields.add(field)
                    inferred_fields.add(field)

        stock_raw = raw.get("stock", "")
        stock = None
        if stock_raw:
            stock_value = _parse_decimal(stock_raw)
            if stock_value is None or stock_value < 0 or stock_value != stock_value.to_integral_value():
                errors.append("Stock invalido; debe ser un entero no negativo.")
            else:
                stock = int(stock_value)
        row_values["stock"] = stock

        image_raw = raw.get("imagen_url", "")
        image_url = None
        if image_raw:
            if re.match(r"^https?://\S+$", image_raw, flags=re.IGNORECASE):
                image_url = image_raw
            else:
                errors.append("URL de imagen invalida; debe iniciar con http:// o https://.")
        row_values["imagen_url"] = image_url

        matched = _match_product(row_values, products_by_sku, products_by_description)
        if category is not None and not (matched is not None and update_mode == "precio_stock"):
            try:
                rule_values = infer_product_fields(category, {
                    "nombre": name,
                    "tipo": row_values.get("tipo"),
                    "forma": row_values.get("forma"),
                    "medida": row_values.get("medida"),
                    "espesor": row_values.get("espesor"),
                    "acabado": finish,
                })
                if matched is not None:
                    old_inferred = infer_product_fields(matched.categoria, {
                        "nombre": matched.nombre,
                        "tipo": matched.tipo,
                        "forma": matched.forma,
                    })
                    for field in ("tipo", "forma", "acabado", "medida", "espesor"):
                        if rule_values.get(field) is None:
                            rule_values[field] = (
                                getattr(matched, field, None) or old_inferred.get(field)
                            )
                if category == ProductCategoryEnum.fierros:
                    rule_values["medida"] = rule_values.get("medida") or rule_values.get("espesor")
                    rule_values["espesor"] = None
                validate_product_fields(category, rule_values)
                for field in ("tipo", "forma", "medida", "espesor"):
                    if row_values.get(field) is None:
                        row_values[field] = rule_values.get(field)
                if category == ProductCategoryEnum.fierros:
                    row_values["medida"] = rule_values.get("medida")
                    row_values["espesor"] = None
            except ValueError as exc:
                errors.append(str(exc))
        duplicate_key = (
            f"sku:{_normalize_match_text(sku).replace(' ', '')}"
            if sku
            else "item:" + "|".join(
                (
                    _normalize_match_text(name),
                    _normalize_match_text(row_values.get("medida")),
                    _normalize_match_text(row_values.get("espesor")),
                )
            )
        )
        if duplicate_key in seen_keys:
            errors.append("Producto duplicado dentro del archivo.")
        seen_keys.add(duplicate_key)

        category_for_price = category
        if matched is not None and update_mode == "precio_stock":
            category_for_price = matched.categoria
        effective_margin = None
        calculated_price = None
        if matched is not None and matched.margen_pct is not None:
            effective_margin = Decimal(str(matched.margen_pct))
        elif category_for_price is not None:
            effective_margin = margins.get(category_for_price.value, Decimal(str(pricing.margen_global_pct)))
        if price_usd is not None and price_usd > 0 and exchange_rate is not None and category_for_price is not None and effective_margin is not None:
            calculated_price = calculate_price_in_pen(
                price_usd,
                exchange_rate,
                effective_margin,
                pricing.costo_incluye_igv,
                pricing.redondeo,
            )
        elif price_usd is not None and price_usd > 0 and exchange_rate is None:
            errors.append("No hay tipo de cambio registrado.")

        if errors:
            status = "ERROR"
        elif category is None:
            status = "REVISAR"
        else:
            status = "ACTUALIZA" if matched else "NUEVO"

        preview_rows.append(
            {
                "row_number": line_number,
                "status": status,
                "motivos": errors or (["Asigna una categoria para continuar."] if category is None else []),
                "inferidos": sorted(inferred_fields),
                "sku": row_values["sku"],
                "nombre": row_values["nombre"],
                "precio_usd": str(price_usd) if price_usd is not None else None,
                "categoria": category.value if category else None,
                "tipo": row_values.get("tipo"),
                "forma": row_values.get("forma"),
                "acabado": finish.value if finish else None,
                "medida": row_values.get("medida"),
                "espesor": row_values.get("espesor"),
                "stock": stock,
                "imagen_url": row_values.get("imagen_url"),
                "precio_final_pen": str(calculated_price) if calculated_price is not None else None,
                "tipo_cambio": str(exchange_rate) if exchange_rate is not None else None,
                "margen_aplicado_pct": str(effective_margin) if effective_margin is not None else None,
                "match_product_id": str(matched.id) if matched else None,
                "match_product_name": matched.nombre if matched else None,
                "provided_fields": sorted(provided_fields),
            }
        )

    return {
        "headers": headers,
        "suggested_mapping": suggested,
        "mapping": selected_mapping,
        "tipo_cambio": str(exchange_rate) if exchange_rate is not None else None,
        "tipo_cambio_fecha": exchange.fecha.isoformat() if exchange else None,
        "rows": preview_rows,
    }


def commit_import(
    db: Session,
    data: bytes,
    filename: str,
    pasted_text: Optional[str],
    mapping: Optional[dict],
    category_overrides: Optional[dict],
    excluded_rows: Sequence[int],
    update_mode: str,
    new_products_active: bool,
    user_email: str,
) -> Tuple[ProductImportHistory, List[str]]:
    if update_mode not in ("todo", "precio_stock"):
        raise ValueError("Modo de actualizacion invalido.")
    preview = build_preview(
        db,
        data=data,
        filename=filename,
        pasted_text=pasted_text,
        mapping=mapping,
        category_overrides=category_overrides,
        update_mode=update_mode,
    )
    excluded = {int(row) for row in excluded_rows}
    products_by_id = {str(product.id): product for product in db.query(Product).all()}
    latest_rate = get_latest_exchange_rate(db)
    pricing = get_pricing_settings(db)
    margins = get_category_margins(db)
    new_count = 0
    updated_count = 0
    errors_count = 0
    changed_ids: List[str] = []

    for row in preview["rows"]:
        if row["row_number"] in excluded:
            continue
        if row["status"] in ("ERROR", "REVISAR"):
            errors_count += 1
            continue

        product = products_by_id.get(row["match_product_id"])
        category = _category(row["categoria"] or "")
        price_usd = _parse_decimal(row["precio_usd"] or "")
        if category is None or price_usd is None or latest_rate is None:
            errors_count += 1
            continue

        if product is None:
            product = Product(
                nombre=row["nombre"],
                categoria=category,
                tipo=row["tipo"],
                forma=row["forma"],
                acabado=ProductAcabadoEnum(row["acabado"]) if row["acabado"] else None,
                medida=row["medida"],
                espesor=row["espesor"],
                precio_unitario=Decimal(row["precio_final_pen"]),
                sku=row["sku"],
                precio_base_usd=price_usd,
                margen_pct=None,
                stock_disponible=row["stock"] if row["stock"] is not None else 0,
                imagen_url=row.get("imagen_url"),
                activo=new_products_active,
                embedding=None,
            )
            db.add(product)
            db.flush()
            new_count += 1
        else:
            product.precio_base_usd = price_usd
            product.precio_unitario = Decimal(row["precio_final_pen"])
            if update_mode == "todo":
                fields = set(row["provided_fields"])
                if "sku" in fields and row["sku"]:
                    product.sku = row["sku"]
                if "nombre" in fields:
                    product.nombre = row["nombre"]
                if "categoria" in fields:
                    product.categoria = category
                if "tipo" in fields:
                    product.tipo = row["tipo"]
                if "forma" in fields:
                    product.forma = row["forma"]
                if "acabado" in fields:
                    product.acabado = ProductAcabadoEnum(row["acabado"]) if row["acabado"] else None
                if "medida" in fields:
                    product.medida = row["medida"]
                if "espesor" in fields:
                    product.espesor = row["espesor"]
                if "stock" in fields and row["stock"] is not None:
                    product.stock_disponible = row["stock"]
                if row.get("imagen_url") and not product.imagen_url:
                    product.imagen_url = row["imagen_url"]
            elif row["stock"] is not None:
                product.stock_disponible = row["stock"]
            updated_count += 1

        changed_ids.append(str(product.id))

    history = ProductImportHistory(
        usuario_email=user_email,
        source_name=_plain_text(filename, 255) if filename else "Tabla pegada",
        nuevos=new_count,
        actualizados=updated_count,
        errores=errors_count,
        indexing_status="queued" if changed_ids else "completed",
        indexing_total=len(changed_ids),
        indexing_completed=0,
    )
    db.add(history)
    db.commit()
    db.refresh(history)
    return history, changed_ids


def index_import_embeddings(import_id: int, product_ids: Sequence[str], session_factory) -> None:
    db = session_factory()
    failed: List[str] = []
    try:
        history = db.query(ProductImportHistory).filter(ProductImportHistory.id == import_id).first()
        if history is None:
            return
        history.indexing_status = "indexing"
        db.commit()

        for start in range(0, len(product_ids), IMPORT_BATCH_SIZE):
            batch_ids = product_ids[start : start + IMPORT_BATCH_SIZE]
            uuid_batch = [UUID(str(product_id)) for product_id in batch_ids]
            products = db.query(Product).filter(Product.id.in_(uuid_batch)).all()
            for product in products:
                vector = []
                for attempt in range(3):
                    vector = generate_product_embedding(product)
                    if any(vector):
                        break
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                if any(vector):
                    product.embedding = vector
                    history.indexing_completed += 1
                else:
                    failed.append(product.sku or product.nombre)
            history.indexing_error = "; ".join(failed)[:2000] or None
            db.commit()
            if start + IMPORT_BATCH_SIZE < len(product_ids):
                time.sleep(1)

        history.indexing_status = "error" if failed else "completed"
        history.indexing_error = "; ".join(failed)[:2000] or None
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error indexando productos de importacion %s", import_id)
        history = db.query(ProductImportHistory).filter(ProductImportHistory.id == import_id).first()
        if history is not None:
            history.indexing_status = "error"
            history.indexing_error = "Fallo inesperado durante la generacion de embeddings."
            db.commit()
    finally:
        db.close()