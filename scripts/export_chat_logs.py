"""Exporta de la BD los mensajes de clientes que AÚN no están etiquetados, listos para revisar a mano.

Genera un CSV con el mismo formato que `chat_real_etiquetado.csv` del APF3. El equipo debe completar la
columna `intencion_gold` (0 consulta, 1 cotización/precio, 2 reclamo/soporte, 3 compra firme) siguiendo la
guía de etiquetado del notebook, y luego pasar el CSV a `scripts/retrain_intent_model.py`.

Uso (desde la raíz del backend, con DATABASE_URL apuntando a la BD de Render):
    python scripts/export_chat_logs.py --salida ml_training/nuevos_chats_para_etiquetar.csv

ADVERTENCIA:
    Los mensajes de `chat_logs` se purgan automáticamente tras los días de retención configurados
    (por defecto 90 días). Es necesario exportarlos con este script y etiquetarlos ANTES de que
    venzan y sean eliminados de la base de datos. Los CSV etiquetados ya versionados en el repositorio
    no se ven afectados por la purga.

Qué hace:
  * toma solo mensajes con rol = user (el texto ya está anonimizado por el backend);
  * omite los ids y los textos que ya están en los CSV etiquetados (ver --excluir);
  * conserva una sola copia de cada texto repetido (los botones sugeridos del chat repiten mensajes);
  * agrega `intencion_sugerida` (lo que predijo el modelo al momento del chat) SOLO como ayuda: la columna
    `intencion_gold` sale VACÍA a propósito. Copiar la sugerencia sin revisarla haría que el modelo se
    entrene con sus propios errores.
"""
import argparse
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db.models import ChatLog, ChatRolEnum
from app.db.session import SessionLocal


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\W+", " ", s).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", default="ml_training/nuevos_chats_para_etiquetar.csv")
    ap.add_argument("--excluir", action="append",
                    help="CSV ya etiquetados cuyos ids/textos se omiten. Repetible. "
                         "Por defecto: ml_training/datos/chat_real_etiquetado.csv y ml_training/*etiquetados*.csv.")
    ap.add_argument("--desde", help="Solo mensajes desde esta fecha (AAAA-MM-DD, UTC).")
    args = ap.parse_args()

    if args.excluir:
        excluir = args.excluir
    else:  # reales ya etiquetados: el original del APF3 + cualquier ml_training/*etiquetados*.csv
        excluir = [str(ROOT / "ml_training/datos/chat_real_etiquetado.csv")]
        excluir += [str(p) for p in sorted((ROOT / "ml_training").glob("*etiquetados*.csv"))]
    ids_vistos, textos_vistos = set(), set()
    for ruta in excluir:
        d = pd.read_csv(ruta)
        ids_vistos |= set(d["id"].astype(str))
        textos_vistos |= set(d["mensaje_texto"].map(_norm))
        print(f"  excluyendo lo ya conocido de {ruta} ({len(d)} filas)")

    stmt = select(ChatLog).where(ChatLog.rol == ChatRolEnum.user).order_by(ChatLog.timestamp.asc())
    if args.desde:
        stmt = stmt.where(ChatLog.timestamp >= pd.Timestamp(args.desde, tz="UTC").to_pydatetime())
    with SessionLocal() as db:
        filas = db.execute(stmt).scalars().all()
        registros = [
            {
                "id": str(f.id),
                "id_conversacion": str(f.id_conversacion),
                "timestamp": f.timestamp.isoformat(sep=" ") if f.timestamp else "",
                "mensaje_texto": f.mensaje_texto,
                "longitud_mensaje": f.longitud_mensaje,
                "contiene_palabra_clave_producto": f.contiene_palabra_clave_producto,
                "intencion_regla_actual": f.intencion_etiquetada,
                "intencion_sugerida": f.intencion_modelo,
                "probabilidad_sugerida": f.probabilidad_modelo,
                "intencion_gold": "",
                "nota_etiquetado": "",
                "etiquetado_por": "",
            }
            for f in filas
        ]
    total = len(registros)
    df = pd.DataFrame(registros)
    if df.empty:
        sys.exit("No hay mensajes de clientes en la BD.")

    df = df[~df["id"].isin(ids_vistos)]
    nuevos_por_id = len(df)
    df["_norm"] = df["mensaje_texto"].map(_norm)
    df = df[~df["_norm"].isin(textos_vistos)]
    df = df.drop_duplicates("_norm", keep="first").drop(columns="_norm")

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(salida, index=False, encoding="utf-8")
    print(f"\nMensajes de clientes en la BD: {total}")
    print(f"  ya etiquetados (por id): {total - nuevos_por_id}")
    print(f"  repetidos o ya conocidos (por texto): {nuevos_por_id - len(df)}")
    print(f"  -> a etiquetar: {len(df)}  guardado en {salida}")
    print("\nSiguiente paso: abrir el CSV, completar `intencion_gold` (0-3) fila por fila y guardar.")


if __name__ == "__main__":
    main()
