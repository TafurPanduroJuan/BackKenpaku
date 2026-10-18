import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv("c:/Users/alexi/Desktop/kenpaku/backend/BackKenpaku/.env")
db_url = os.getenv("DATABASE_URL")
engine = create_engine(db_url)

with engine.connect() as conn:
    print("Checking orders table columns...")
    res = conn.execute(text("""
        SELECT column_name, is_nullable, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'orders' AND column_name IN ('cliente_correo', 'cliente_nombre', 'cliente_telefono', 'canal_venta');
    """))
    for row in res.fetchall():
        print(row)

    print("\nAltering cliente_correo to DROP NOT NULL in orders table...")
    conn.execute(text("ALTER TABLE orders ALTER COLUMN cliente_correo DROP NOT NULL;"))
    conn.commit()
    print("Successfully altered cliente_correo to be nullable!")

    print("\nVerifying updated columns...")
    res = conn.execute(text("""
        SELECT column_name, is_nullable 
        FROM information_schema.columns 
        WHERE table_name = 'orders' AND column_name = 'cliente_correo';
    """))
    for row in res.fetchall():
        print("Updated:", row)
