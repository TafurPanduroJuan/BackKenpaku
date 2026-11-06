from app.db.models import ProductCategoryEnum


PRODUCT_FIELD_RULES = {
    ProductCategoryEnum.tubos: {
        "required": ["forma", "medida", "espesor", "acabado"],
        "optional": ["tipo"],
        "hidden_by_default": [],
    },
    ProductCategoryEnum.perfiles: {
        "required": ["tipo", "medida", "espesor"],
        "optional": ["forma", "acabado"],
        "hidden_by_default": [],
    },
    ProductCategoryEnum.planchas: {
        "required": ["tipo", "medida", "espesor"],
        "optional": ["forma", "acabado"],
        "hidden_by_default": [],
    },
    ProductCategoryEnum.fierros: {
        "required": ["tipo", "medida"],
        "optional": ["forma", "acabado"],
        "hidden_by_default": ["espesor"],
    },
    ProductCategoryEnum.accesorios: {
        "required": [],
        "optional": ["tipo", "forma", "medida", "espesor", "acabado"],
        "hidden_by_default": ["tipo", "forma", "medida", "espesor", "acabado"],
    },
}

def infer_product_fields(category, values):
    name = str(values.get("nombre") or "").casefold()
    if category == ProductCategoryEnum.tubos and not values.get("forma"):
        for shape in ("cuadrado", "rectangular", "redondo"):
            if shape in name:
                values["forma"] = shape
                break

    if not values.get("tipo"):
        category_terms = {
            ProductCategoryEnum.perfiles: ("ángulo", "angulo", "platina", "canal", "viga"),
            ProductCategoryEnum.planchas: ("galvanizada", "lac", "laf"),
            ProductCategoryEnum.fierros: ("corrugado", "liso", "cuadrado"),
        }
        for term in category_terms.get(category, ()):
            if term in name:
                values["tipo"] = term
                break
    return values


def validate_product_fields(category, values):
    values = infer_product_fields(category, values)
    rules = PRODUCT_FIELD_RULES[category]
    missing = [
        field
        for field in rules["required"]
        if values.get(field) is None or not str(values[field]).strip()
    ]
    if missing:
        labels = {
            "forma": "forma",
            "tipo": "tipo",
            "medida": "medida o diámetro",
            "espesor": "espesor",
            "acabado": "acabado",
        }
        raise ValueError(
            "Completa los campos obligatorios para esta categoría: "
            + ", ".join(labels[field] for field in missing)
            + "."
        )

    if category == ProductCategoryEnum.fierros:
        values["espesor"] = None
