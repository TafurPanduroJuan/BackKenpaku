"""Reentrena el modelo de intención del chat (APF3) con los chats reales NUEVOS ya etiquetados.

Replica el pipeline del notebook (misma semilla, mismas variables, misma partición agrupada por
conversación, mismos 4 modelos con GridSearchCV y la misma regla de selección), pero usando:
  * mensajes REALES etiquetados a mano (columna `intencion_gold`) de uno o más CSV, y
  * los mensajes SIMULADOS del dataset base del APF3 (se conservan para tener ejemplos de las 4 clases).

NO sobrescribe el modelo en producción: escribe un modelo CANDIDATO en --out (por defecto
app/ml/model_candidate). Revise las métricas y, si le convence, cópielo a app/ml/model/.

Uso (desde la raíz del backend):
    python scripts/retrain_intent_model.py \\
        --real ml_training/datos/chat_real_etiquetado.csv \\
        --real ml_training/nuevos_chats_etiquetados.csv

Regla de oro: `intencion_gold` debe ser una etiqueta REVISADA POR PERSONAS. Entrenar con las
predicciones del propio modelo (columna `intencion_sugerida`) sin revisarlas lo haría aprender sus errores.
"""
import argparse
import json
import re
import sys
import unicodedata
import warnings
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
    precision_recall_fscore_support,
    recall_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedGroupKFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ml.intent_features import FeaturasMensaje
from app.services.rag_service import classify_intention

warnings.filterwarnings("ignore")
SEED = 42
UMBRAL = 0.50
CLASES = {0: "Consulta general", 1: "Cotización/Precio", 2: "Reclamo/Soporte", 3: "Compra firme"}
ACCION = {0: "responder_con_asesor_ia", 1: "ofrecer_proforma_y_registrar_cotizacion",
          2: "derivar_a_humano_por_whatsapp_y_alertar_telegram", 3: "alerta_prioritaria_al_administrador"}
RAW = ["mensaje_texto", "timestamp", "longitud_mensaje", "contiene_palabra_clave_producto"]
COLS = ["id", "id_conversacion", "timestamp", "mensaje_texto", "longitud_mensaje",
        "contiene_palabra_clave_producto", "intencion_etiquetada", "origen"]
REQUERIDAS = ["id", "id_conversacion", "timestamp", "mensaje_texto", "longitud_mensaje",
              "contiene_palabra_clave_producto", "intencion_gold"]


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\W+", " ", s).strip()


def cargar_reales(rutas) -> pd.DataFrame:
    partes = []
    for ruta in rutas:
        d = pd.read_csv(ruta)
        faltan = [c for c in REQUERIDAS if c not in d.columns]
        if faltan:
            sys.exit(f"[ERROR] {ruta}: faltan columnas {faltan}")
        total = len(d)
        d["intencion_gold"] = pd.to_numeric(d["intencion_gold"], errors="coerce")
        sin_etiqueta = int(d["intencion_gold"].isna().sum())
        invalidas = int((~d["intencion_gold"].dropna().isin(CLASES)).sum())
        if invalidas:
            sys.exit(f"[ERROR] {ruta}: hay {invalidas} etiquetas fuera de 0-3")
        d = d.dropna(subset=["intencion_gold"])
        print(f"  {ruta}: {total} filas, {len(d)} etiquetadas (se omiten {sin_etiqueta} sin etiqueta)")
        partes.append(d)
    real = pd.concat(partes, ignore_index=True)
    antes = len(real)
    real = real.drop_duplicates("id", keep="last")  # si un mismo id está en 2 archivos, gana el último
    if len(real) < antes:
        print(f"  ids repetidos entre archivos: {antes - len(real)} (se conserva la última versión)")
    real["intencion_etiquetada"] = real["intencion_gold"].astype(int)
    real["origen"] = "real"
    return real[COLS]


def cargar_simulados(ruta) -> pd.DataFrame:
    base = pd.read_csv(ruta)
    sim = base[base["origen"] == "simulado"].copy()
    sim["intencion_etiquetada"] = sim["intencion_etiquetada"].astype(int)
    return sim[COLS]


def nuevo_preproceso():
    return ColumnTransformer([
        ("tfidf_palabras", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, strip_accents="unicode"), "texto"),
        ("tfidf_caracteres", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True, strip_accents="unicode"), "texto"),
        ("num_escalado", StandardScaler(), ["longitud", "n_numeros"]),
        ("binarias", "passthrough", ["prod_kw", "tiene_codigo", "fuera_horario", "es_lista"]),
    ])


def nuevo_pipeline(clf):
    return Pipeline([("feat", FeaturasMensaje()), ("prep", nuevo_preproceso()), ("clf", clf)])


def metricas(y, p):
    pr, rc, f1, _ = precision_recall_fscore_support(y, p, average="macro", zero_division=0)
    rec = recall_score(y, p, labels=[0, 1, 2, 3], average=None, zero_division=0)
    return {"accuracy": accuracy_score(y, p), "precision_macro": pr, "recall_macro": rc, "F1_macro": f1,
            "recall_reclamo": rec[2], "recall_compra": rec[3]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real", action="append", required=True,
                    help="CSV con mensajes reales etiquetados (columna intencion_gold). Repetible.")
    ap.add_argument("--base-simulado", default=str(ROOT / "ml_training/datos/dataset_base_intencion_kenpaku.csv"),
                    help="Dataset del APF3 del que se toman SOLO las filas simuladas.")
    ap.add_argument("--out", default=str(ROOT / "app/ml/model_candidate"), help="Carpeta del modelo candidato.")
    args = ap.parse_args()

    print("== 1. Datos")
    real = cargar_reales(args.real)
    sim = cargar_simulados(args.base_simulado)
    df = pd.concat([real, sim], ignore_index=True)
    n0 = len(df)
    df["_norm"] = df["mensaje_texto"].map(_norm)
    df = df[df["mensaje_texto"].notna() & (df["mensaje_texto"].str.strip() != "")]
    # Duplicados: los botones sugeridos del chat repiten textos; se conserva la primera aparición (evita fuga train/test)
    df = df.drop_duplicates("_norm", keep="first").drop(columns="_norm").reset_index(drop=True)
    print(f"  filas iniciales {n0} -> finales {len(df)} (duplicados eliminados {n0 - len(df)})")
    print(pd.crosstab(df.intencion_etiquetada.map(CLASES), df.origen, margins=True).to_string())
    minoritaria = df.intencion_etiquetada.value_counts().min()
    if minoritaria < 30:
        print(f"  [ADVERTENCIA] clase minoritaria con solo {minoritaria} ejemplos (mínimo recomendado: 30)")
    reales_por_clase = df[df.origen == "real"].intencion_etiquetada.value_counts().reindex(range(4), fill_value=0)
    for k, n in reales_por_clase.items():
        if n == 0:
            print(f"  [ADVERTENCIA] 0 mensajes REALES de '{CLASES[k]}': su desempeño no se podrá validar con chats reales")

    print("\n== 2. Partición 80/20 estratificada y agrupada por conversación")
    X_all, y_all, g_all = df[RAW], df["intencion_etiquetada"].values, df["id_conversacion"].values
    tr_idx, te_idx = next(StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED).split(X_all, y_all, groups=g_all))
    X_tr, y_tr, g_tr = X_all.iloc[tr_idx], y_all[tr_idx], g_all[tr_idx]
    X_te, y_te = X_all.iloc[te_idx], y_all[te_idx]
    df_te = df.iloc[te_idx]
    print(f"  entrenamiento {len(X_tr)} | prueba {len(X_te)} | reales en prueba {int((df_te.origen == 'real').sum())}")

    print("\n== 3. Búsqueda de hiperparámetros (validación cruzada solo sobre entrenamiento)")
    cv_splits = list(StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED).split(X_tr, y_tr, groups=g_tr))
    espacios = {
        "Regresión logística": (LogisticRegression(max_iter=3000, class_weight="balanced", random_state=SEED), {"clf__C": [0.1, 1, 10, 100]}),
        "SVM lineal": (LinearSVC(class_weight="balanced", random_state=SEED, max_iter=20000), {"clf__C": [0.01, 0.1, 1, 10]}),
        "KNN (coseno)": (KNeighborsClassifier(metric="cosine", algorithm="brute"), {"clf__n_neighbors": [3, 5, 7, 11]}),
        "Árbol de decisión": (DecisionTreeClassifier(class_weight="balanced", random_state=SEED),
                              {"clf__max_depth": [3, 5, 8, None], "clf__min_samples_leaf": [1, 3, 5]}),
    }
    buscadores = {}
    for nombre, (clf, grid) in espacios.items():
        gs = GridSearchCV(nuevo_pipeline(clf), grid, cv=cv_splits, scoring="f1_macro", refit=True, n_jobs=1)
        gs.fit(X_tr, y_tr)
        buscadores[nombre] = gs
        print(f"  {nombre:22s} F1 macro CV = {gs.best_score_:.3f}  {gs.best_params_}")
    cv_scores = {n: g.best_score_ for n, g in buscadores.items()}
    # Solo modelos con predict_proba son elegibles: el backend usa el umbral de confianza y, sin probabilidades,
    # caería en silencio a la regla de palabras clave. El SVM lineal se evalúa pero no se exporta.
    elegibles = {n: s for n, s in cv_scores.items() if hasattr(buscadores[n].best_estimator_, "predict_proba")}
    mejor_cv = max(elegibles.values())
    preferencia = [n for n in ["Regresión logística", "SVM lineal", "KNN (coseno)", "Árbol de decisión"] if n in elegibles]
    elegido = next(n for n in preferencia if cv_scores[n] >= mejor_cv - 0.01)  # regla fijada ANTES de ver la prueba
    print(f"  -> seleccionado: {elegido}")

    print("\n== 4. Evaluación en prueba (uso único)")
    dummy = nuevo_pipeline(DummyClassifier(strategy="most_frequent")).fit(X_tr, y_tr)
    pred = {"Línea base: clase más frecuente": dummy.predict(X_te),
            "Línea base: regla actual del MVP": X_te["mensaje_texto"].map(classify_intention).values}
    for n, g in buscadores.items():
        pred[n] = g.predict(X_te)
    tabla = pd.DataFrame({n: metricas(y_te, p) for n, p in pred.items()}).T
    tabla["seleccionado"] = ["sí" if n == elegido else "" for n in tabla.index]
    print(tabla.round(3).to_string())

    final = buscadores[elegido].best_estimator_
    p_final = pred[elegido]
    f1_final, acc_final = f1_score(y_te, p_final, average="macro"), accuracy_score(y_te, p_final)
    print("\n" + classification_report(y_te, p_final, target_names=list(CLASES.values()), zero_division=0))
    if max(f1_final, acc_final) >= 0.98:
        print("  [ADVERTENCIA] métricas >= 0.98: revisar posible fuga o datos demasiado fáciles")

    mask_real = (df_te.origen == "real").values
    print(f"== 5. Solo filas REALES de prueba (n={int(mask_real.sum())}) — la comparación que más importa")
    if mask_real.sum():
        regla_te = pred["Línea base: regla actual del MVP"]
        print(f"  accuracy modelo = {accuracy_score(y_te[mask_real], p_final[mask_real]):.3f} | "
              f"accuracy regla = {accuracy_score(y_te[mask_real], regla_te[mask_real]):.3f}")
        for k in (2, 3):
            n_k = int((y_te[mask_real] == k).sum())
            if n_k:
                rm = recall_score(y_te[mask_real] == k, p_final[mask_real] == k)
                rr = recall_score(y_te[mask_real] == k, regla_te[mask_real] == k)
                print(f"  recall '{CLASES[k]}' en reales: modelo {rm:.2f} vs regla {rr:.2f} (n={n_k})")
            else:
                print(f"  recall '{CLASES[k]}' en reales: sin ejemplos reales en la prueba")
    if mask_real.sum() < 20:
        print("  [ADVERTENCIA] menos de 20 filas reales en prueba: las métricas reales son solo indicativas")

    print("\n== 6. Exportación del modelo CANDIDATO")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, out / "intent_model.joblib", compress=3)
    meta = {"modelo": elegido, "parametros": {k: str(v) for k, v in buscadores[elegido].best_params_.items()},
            "clases": CLASES, "umbral_confianza": UMBRAL, "acciones": ACCION, "semilla": SEED,
            "sklearn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__,
            "filas_entrenamiento": len(X_tr), "filas_prueba": len(X_te),
            "F1_macro_prueba": round(float(f1_final), 4), "accuracy_prueba": round(float(acc_final), 4),
            "filas_reales": int((df.origen == "real").sum()), "filas_simuladas": int((df.origen == "simulado").sum()),
            "fecha_entrenamiento": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "advertencia": f"Entrenado con {int((df.origen == 'real').sum())} mensajes reales + "
                           f"{int((df.origen == 'simulado').sum())} simulados; resultados indicativos hasta validar con más chats reales."}
    (out / "intent_model_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tabla.round(4).to_csv(out / "tabla_prueba.csv")
    print(f"  guardado en {out}  ({(out / 'intent_model.joblib').stat().st_size / 1024:.0f} KB)")
    print(f"  Para ponerlo en producción:  cp {out}/intent_model.joblib {out}/intent_model_meta.json app/ml/model/")


if __name__ == "__main__":
    main()
