from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.db.models import ProductCategoryEnum


MeasurementKind = Literal["dimension", "espesor"]


class MeasurementEquivalenceInput(BaseModel):
    tipo_medida: MeasurementKind
    pulgada: str = Field(min_length=1, max_length=20)
    mm_minimo: Decimal = Field(gt=0, decimal_places=3)
    mm_maximo: Decimal = Field(gt=0, decimal_places=3)
    categoria: Optional[ProductCategoryEnum] = None
    tolerancia_mm: Decimal = Field(
        default=Decimal("1.5"), ge=0, le=10, decimal_places=2
    )

    @model_validator(mode="after")
    def validate_range(self):
        if self.mm_minimo > self.mm_maximo:
            raise ValueError("El mínimo en mm no puede ser mayor que el máximo.")
        return self


class MeasurementEquivalenceResponse(MeasurementEquivalenceInput):
    id: int


class MeasurementEquivalencesUpdate(BaseModel):
    items: List[MeasurementEquivalenceInput] = Field(min_length=1, max_length=100)


class MeasurementEquivalencesResponse(BaseModel):
    items: List[MeasurementEquivalenceResponse]
