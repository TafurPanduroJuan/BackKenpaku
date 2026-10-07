from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Product, ProductAcabadoEnum, ProductCategoryEnum
from app.db.session import get_db
from app.schemas.product import (
    ProductPaginatedResponse,
    ProductResponse,
    compute_stock_estado,
)

router = APIRouter(prefix="/api/products", tags=["Products"])


@router.get("", response_model=ProductPaginatedResponse)
def get_products(
    q: Optional[str] = Query(None, description="Término de búsqueda"),
    categoria: Optional[ProductCategoryEnum] = Query(
        None, description="Filtro por categoría"
    ),
    acabado: Optional[ProductAcabadoEnum] = Query(
        None, description="Filtro por acabado"
    ),
    min_precio: Optional[Decimal] = Query(
        None, ge=0, description="Precio mínimo en PEN"
    ),
    max_precio: Optional[Decimal] = Query(
        None, ge=0, description="Precio máximo en PEN"
    ),
    solo_stock: bool = Query(
        False, description="Filtrar solo productos con stock disponible"
    ),
    orden: str = Query(
        "relevancia",
        pattern="^(relevancia|precio_asc|precio_desc|nombre)$",
        description="Criterio de ordenamiento",
    ),
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(12, ge=1, le=100, description="Tamaño de página"),
    db: Session = Depends(get_db),
):
    """Obtiene el catálogo de productos activos filtrado y paginado."""
    query = db.query(Product).filter(Product.activo == True)

    if q:
        search_pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Product.nombre.ilike(search_pattern),
                Product.descripcion_corta.ilike(search_pattern),
                Product.ficha_tecnica.ilike(search_pattern),
                Product.medida.ilike(search_pattern),
            )
        )

    if categoria:
        query = query.filter(Product.categoria == categoria)

    if acabado:
        query = query.filter(Product.acabado == acabado)

    if min_precio is not None:
        query = query.filter(Product.precio_unitario >= min_precio)

    if max_precio is not None:
        query = query.filter(Product.precio_unitario <= max_precio)

    if solo_stock:
        query = query.filter(Product.stock_disponible > 0)

    # Ordenamiento
    if orden == "precio_asc":
        query = query.order_by(Product.precio_unitario.asc())
    elif orden == "precio_desc":
        query = query.order_by(Product.precio_unitario.desc())
    elif orden == "nombre":
        query = query.order_by(Product.nombre.asc())
    else:  # relevancia
        query = query.order_by(Product.created_at.desc())

    total = query.count()
    offset = (page - 1) * page_size
    items_db = query.offset(offset).limit(page_size).all()

    items_response = []
    for item in items_db:
        resp = ProductResponse(
            id=item.id,
            nombre=item.nombre,
            categoria=item.categoria,
            acabado=item.acabado,
            medida=item.medida,
            espesor=item.espesor,
            descripcion_corta=item.descripcion_corta,
            ficha_tecnica=item.ficha_tecnica,
            precio_unitario=item.precio_unitario,
            stock_disponible=item.stock_disponible,
            stock_estado=compute_stock_estado(item.stock_disponible),
            imagen_url=item.imagen_url,
        )
        items_response.append(resp)

    return ProductPaginatedResponse(
        items=items_response, total=total, page=page, page_size=page_size
    )


@router.get("/{product_id}", response_model=ProductResponse)
def get_product_by_id(product_id: UUID, db: Session = Depends(get_db)):
    """Obtiene el detalle de un producto específico por su UUID."""
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.activo == True)
        .first()
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Producto no encontrado", "code": "NOT_FOUND"},
        )

    return ProductResponse(
        id=product.id,
        nombre=product.nombre,
        categoria=product.categoria,
        acabado=product.acabado,
        medida=product.medida,
        espesor=product.espesor,
        descripcion_corta=product.descripcion_corta,
        ficha_tecnica=product.ficha_tecnica,
        precio_unitario=product.precio_unitario,
        stock_disponible=product.stock_disponible,
        stock_estado=compute_stock_estado(product.stock_disponible),
        imagen_url=product.imagen_url,
    )
