"""Características del mensaje para el modelo de intención (Kenpaku, APF3).
Debe estar disponible en el entorno donde se cargue el modelo exportado (notebook y backend)."""
import re
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

PRODUCT_KW = ["tubo", "plancha", "perfil", "angulo", "ángulo", "fierro", "laf", "lac", "galvanizado", "corrugado"]


class FeaturasMensaje(BaseEstimator, TransformerMixin):
    """Recibe un DataFrame con: mensaje_texto, timestamp (ISO, UTC) y opcionalmente
    longitud_mensaje y contiene_palabra_clave_producto (campos que ya captura el MVP)."""

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        X = pd.DataFrame(X).copy()
        txt = X["mensaje_texto"].fillna("").astype(str)
        if "timestamp" in X.columns:
            ts = pd.to_datetime(X["timestamp"], utc=True, format="ISO8601", errors="coerce").dt.tz_convert("America/Lima")
        else:
            ts = pd.Series(pd.NaT, index=X.index)
        hora, dow = ts.dt.hour, ts.dt.dayofweek
        fuera = ((dow == 6) | (hora < 8) | (hora >= 18)).fillna(False).astype(int)
        if "contiene_palabra_clave_producto" in X.columns:
            prod = X["contiene_palabra_clave_producto"].fillna(False).astype(int)
        else:
            prod = txt.str.lower().map(lambda s: int(any(k in s for k in PRODUCT_KW)))
        nums = txt.str.count(r"\d+(?:[.,]\d+)?")
        out = pd.DataFrame({
            "texto": txt,
            "longitud": txt.str.len(),
            "n_numeros": nums,
            "prod_kw": prod.values,
            "tiene_codigo": txt.str.contains(r"KP-|\[DNI\]", regex=True).astype(int),
            "fuera_horario": fuera.values,
            "es_lista": (txt.str.contains(r"\n|\\n", regex=True) | (nums >= 4)).astype(int),
        })
        return out
