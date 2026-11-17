"""Modelo de intención del chat (APF3). Carga el pipeline exportado con joblib y predice un mensaje.

Contrato (igual al del notebook): entrada = campos que el MVP ya captura; salida = intención,
probabilidad, bandera de baja confianza y acción sugerida.

Garantías de operación:
* Si el modelo está apagado (ML_INTENT_ENABLED=false) o falla, el chat NUNCA se detiene:
  `predecir_intencion` cae a la regla de palabras clave y `predecir_intencion_o_none` devuelve None.
* Si la carga falla una vez, no se reintenta en cada mensaje (se registra una sola vez);
  se recupera al reiniciar el servicio.
"""
import json
import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent / "ml" / "model"
CLASES = {0: "Consulta general", 1: "Cotización/Precio", 2: "Reclamo/Soporte", 3: "Compra firme"}
RAW = ["mensaje_texto", "timestamp", "longitud_mensaje", "contiene_palabra_clave_producto"]

_estado = {"fallo_carga": False}


@lru_cache(maxsize=1)
def _cargar():
    import joblib

    import app.ml.intent_features as feats

    # El notebook guardó el pipeline referenciando el módulo "intent_features" (sin paquete).
    sys.modules.setdefault("intent_features", feats)
    meta = json.loads((MODEL_DIR / "intent_model_meta.json").read_text(encoding="utf-8"))
    modelo = joblib.load(MODEL_DIR / "intent_model.joblib")
    return modelo, meta


def _modelo():
    if _estado["fallo_carga"]:
        raise RuntimeError("Modelo de intención no disponible (falló la carga; reinicie el servicio)")
    try:
        return _cargar()
    except Exception:
        _estado["fallo_carga"] = True
        raise


def precargar_modelo() -> bool:
    """Carga el modelo al iniciar la app para que el primer chat no pague el costo de importar sklearn."""
    if not settings.ML_INTENT_ENABLED:
        logger.info("Modelo de intención desactivado (ML_INTENT_ENABLED=false)")
        return False
    try:
        _, meta = _modelo()
        logger.info("Modelo de intención cargado: %s (F1 macro prueba %s)", meta.get("modelo"), meta.get("F1_macro_prueba"))
        return True
    except Exception:
        logger.exception("No se pudo cargar el modelo de intención; el chat usará la regla de palabras clave")
        return False


def _predecir_con_modelo(registro: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    modelo, meta = _modelo()
    entrada = pd.DataFrame([{k: registro.get(k) for k in RAW}])
    proba = modelo.predict_proba(entrada)[0]
    k = int(np.argmax(proba))
    conf = float(proba[k])
    baja = conf < meta["umbral_confianza"]
    acciones = {int(i): a for i, a in meta["acciones"].items()}
    return {
        "intencion_id": k,
        "intencion": CLASES[k],
        "probabilidad": round(conf, 3),
        "baja_confianza": bool(baja),
        "accion": acciones[0] if baja else acciones[k],
    }


def predecir_intencion_o_none(registro: dict[str, Any]) -> dict[str, Any] | None:
    """Predicción del modelo, o None si está apagado/no disponible (no inventa una predicción)."""
    if not settings.ML_INTENT_ENABLED:
        return None
    try:
        return _predecir_con_modelo(registro)
    except Exception:
        if not _estado["fallo_carga"]:
            logger.exception("Falló la predicción del modelo de intención")
        return None


def predecir_intencion(registro: dict[str, Any]) -> dict[str, Any]:
    """Devuelve intencion_id, intencion, probabilidad, baja_confianza y accion. Siempre responde."""
    resultado = predecir_intencion_o_none(registro)
    if resultado is not None:
        return resultado

    from app.services.rag_service import classify_intention

    k = classify_intention(registro.get("mensaje_texto", "") or "")
    return {
        "intencion_id": k,
        "intencion": CLASES[k],
        "probabilidad": 0.0,
        "baja_confianza": True,
        "accion": "responder_con_asesor_ia",
    }