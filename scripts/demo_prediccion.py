"""Demo de la llamada real al modelo exportado. Ejecutar desde la raíz del backend:
    python scripts/demo_prediccion.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.intent_model import predecir_intencion  # noqa: E402

registro = {"mensaje_texto": "Buenas noches, mi pedido llegó con los tubos doblados, quiero que lo cambien",
            "timestamp": "2026-11-13 02:30:00+00:00", "longitud_mensaje": 71, "contiene_palabra_clave_producto": True}
print("ENTRADA:", json.dumps(registro, ensure_ascii=False))
print("SALIDA :", json.dumps(predecir_intencion(registro), ensure_ascii=False))
