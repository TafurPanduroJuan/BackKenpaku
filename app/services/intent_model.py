"""Modelo de intención del chat (APF3). Carga el pipeline exportado con joblib y predice un mensaje.

Si el modelo no está disponible o falla, cae a la regla de palabras clave (classify_intention)
para que el chat nunca se detenga por el modelo.
"""
import json
import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent / "ml" / "model"
CLASES = {0: "Consulta general", 1: "Cotización/Precio", 2: "Reclamo/Soporte", 3: "Compra firme"}
RAW = ["mensaje_texto", "timestamp", "longitud_mensaje", "contiene_palabra_clave_producto"]


@lru_cache(maxsize=1)
def _cargar():
    import joblib

    import app.ml.intent_features as feats

    # El pipeline se guardó en el notebook referenciando el módulo "intent_features"
    sys.modules.setdefault("intent_features", feats)
    meta = json.loads((MODEL_DIR / "intent_model_meta.json").read_text(encoding="utf-8"))
    modelo = joblib.load(MODEL_DIR / "intent_model.joblib")
    return modelo, meta


def predecir_intencion(registro: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve intencion_id, intencion, probabilidad, baja_confianza y accion."""
    try:
        import numpy as np
        import pandas as pd

        modelo, meta = _cargar()
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
    except Exception:  # noqa: BLE001 - el chat no debe caerse por el modelo
        logger.exception("Modelo de intención no disponible; se usa la regla de palabras clave")
        from app.services.rag_service import classify_intention

        k = classify_intention(registro.get("mensaje_texto", ""))
        return {"intencion_id": k, "intencion": CLASES[k], "probabilidad": 0.0,
                "baja_confianza": True, "accion": "responder_con_asesor_ia"}
