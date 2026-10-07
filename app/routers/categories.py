from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Product, ProductCategoryEnum
from app.db.session import get_db
from app.schemas.product import CategorySummary

router = APIRouter(prefix="/api/categories", tags=["Categories"])

CATEGORY_METADATA = {
    ProductCategoryEnum.tubos: {
        "nombre": "Tubos de Acero",
        "descripcion": "Tubos redondos, cuadrados y rectangulares de acero negro y galvanizado.",
    },
    ProductCategoryEnum.planchas: {
        "nombre": "Planchas de Acero",
        "descripcion": "Planchas de acero laminado en frío (LAF), en caliente (LAC) y galvanizadas.",
    },
    ProductCategoryEnum.perfiles: {
        "nombre": "Perfiles Estructurales",
        "descripcion": "Ángulos, platinas, canales U y perfiles estructurales de alta resistencia.",
    },
    ProductCategoryEnum.fierros: {
        "nombre": "Fierros de Construcción",
        "descripcion": "Fierros corrugados Grado 60, alambres y barras de construcción.",
    },
    ProductCategoryEnum.accesorios: {
        "nombre": "Accesorios y Complementos",
        "descripcion": "Discos de corte, soldaduras, bridas y accesorios complementarios.",
    },
}


@router.get("", response_model=List[CategorySummary])
def get_categories(db: Session = Depends(get_db)):
    """Retorna las categorías con el conteo de productos activos en cada una."""
    counts = (
        db.query(Product.categoria, func.count(Product.id).label("total"))
        .filter(Product.activo == True)
        .group_by(Product.categoria)
        .all()
    )
    count_dict = {cat: total for cat, total in counts}

    result = []
    for cat in ProductCategoryEnum:
        meta = CATEGORY_METADATA.get(
            cat,
            {
                "nombre": cat.value.capitalize(),
                "descripcion": f"Productos de {cat.value}",
            },
        )
        total = count_dict.get(cat, 0)
        result.append(
            CategorySummary(
                slug=cat.value,
                nombre=meta["nombre"],
                descripcion=meta["descripcion"],
                total=total,
            )
        )
    return result
