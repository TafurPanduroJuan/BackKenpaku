import secrets
import sys
from pathlib import Path

# Añadir la raíz del proyecto al sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db.session import engine

def run_migration():
    print("[MIGRATION] Iniciando migracion de Fase 1 en Supabase PostgreSQL...")
    
    # 1. Agregar nuevos estados a orderestadoenum (requiere autocommit en PostgreSQL)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for val in ["flete_cotizado", "despachado", "listo_para_recojo"]:
            try:
                conn.execute(text(f"ALTER TYPE orderestadoenum ADD VALUE IF NOT EXISTS '{val}';"))
                print(f"[OK] Estado '{val}' anadido a orderestadoenum")
            except Exception as e:
                print(f"[INFO] Estado '{val}': {e}")

    # 2. Agregar nuevas columnas a la tabla orders y crear tabla order_events
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("""
            ALTER TABLE orders ADD COLUMN IF NOT EXISTS costo_flete NUMERIC(10, 2) DEFAULT 0.00;
            ALTER TABLE orders ADD COLUMN IF NOT EXISTS estado_flete VARCHAR(50) DEFAULT 'sin_cotizar';
            ALTER TABLE orders ADD COLUMN IF NOT EXISTS tracking_token VARCHAR(64) UNIQUE;
            ALTER TABLE orders ADD COLUMN IF NOT EXISTS fecha_pago TIMESTAMP WITH TIME ZONE;
            ALTER TABLE orders ADD COLUMN IF NOT EXISTS voucher_referencia TEXT;

            CREATE TABLE IF NOT EXISTS order_events (
                id UUID PRIMARY KEY,
                order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                estado_anterior VARCHAR(50),
                estado_nuevo VARCHAR(50) NOT NULL,
                nota TEXT,
                autor VARCHAR(50) NOT NULL DEFAULT 'sistema',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS ix_order_events_order_id ON order_events(order_id);
        """))
        print("[OK] Columnas en 'orders' y tabla 'order_events' creadas exitosamente.")

        # 3. Asignar tracking_token a pedidos existentes que no tengan uno
        existing_orders = conn.execute(text("SELECT id FROM orders WHERE tracking_token IS NULL;")).fetchall()
        for row in existing_orders:
            token = f"kpk_{secrets.token_urlsafe(16)}"
            conn.execute(
                text("UPDATE orders SET tracking_token = :token WHERE id = :order_id;"),
                {"token": token, "order_id": row[0]}
            )
            print(f"[TOKEN] Asignado al pedido {row[0]}: {token}")

    print("[SUCCESS] Migracion de Fase 1 completada con exito.")

if __name__ == "__main__":
    run_migration()
