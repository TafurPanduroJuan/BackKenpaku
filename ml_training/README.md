# ml_training — datos y reentrenamiento del modelo de intención (APF3)

- `datos/chat_real_etiquetado.csv`: 60 mensajes reales (anonimizados) etiquetados en el APF3.
- `datos/dataset_base_intencion_kenpaku.csv`: dataset del APF3; del que solo se usan las filas simuladas.
- Flujo: `scripts/export_chat_logs.py` → etiquetar `intencion_gold` a mano → `scripts/retrain_intent_model.py`.
- Guardar los CSV etiquetados nuevos aquí como `ml_training/<nombre>_etiquetados.csv`.
- Si el repositorio es público, considera no subir CSV con chats reales (están anonimizados, pero son conversaciones de clientes).
