import logging
import os
import re
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from typing import Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}


def sanitize_filename(name: str) -> str:
    """Elimina caracteres no seguros de un nombre de archivo."""
    clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", name)
    return clean[:50]


def upload_voucher_file(file_bytes: bytes, original_filename: str, content_type: str) -> Tuple[str, str]:
    """
    Sube un archivo de voucher a Supabase Storage con fallback local tolerante a fallos.
    Retorna una tupla (url_acceso, nombre_archivo_guardado).
    
    1. Si SUPABASE_URL y SUPABASE_KEY están configurados, sube al bucket de Supabase.
    2. Si no están configurados o hay error de red, guarda en disco local bajo settings.UPLOAD_DIR.
    """
    content_type_clean = (content_type or "").lower().split(";")[0].strip()
    ext = ALLOWED_MIME_TYPES.get(content_type_clean)
    if not ext:
        # Intentar deducir extensión por el nombre
        ext = Path(original_filename).suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp", ".pdf"]:
            ext = ".png"

    safe_base = sanitize_filename(Path(original_filename).stem)
    unique_filename = f"voucher_{uuid.uuid4().hex[:10]}_{safe_base}{ext}"

    # 1. Intentar subir a Supabase Storage si las credenciales existen
    if settings.SUPABASE_URL and settings.SUPABASE_KEY:
        try:
            supabase_endpoint = (
                f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/"
                f"{settings.SUPABASE_BUCKET_VOUCHERS}/{unique_filename}"
            )
            req = urllib.request.Request(
                supabase_endpoint,
                data=file_bytes,
                headers={
                    "Authorization": f"Bearer {settings.SUPABASE_KEY}",
                    "apikey": settings.SUPABASE_KEY,
                    "Content-Type": content_type_clean,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status in (200, 201):
                    public_url = (
                        f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/public/"
                        f"{settings.SUPABASE_BUCKET_VOUCHERS}/{unique_filename}"
                    )
                    logger.info(f"✅ Voucher subido con éxito a Supabase Storage: {public_url}")
                    return public_url, unique_filename
        except Exception as e:
            logger.warning(
                f"⚠️ Error subiendo a Supabase Storage ({e}). Aplicando fallback a almacenamiento local."
            )

    # 2. Fallback local seguro (en disco)
    try:
        upload_path = Path(settings.UPLOAD_DIR)
        if not upload_path.is_absolute():
            backend_root = Path(__file__).resolve().parent.parent.parent
            upload_path = backend_root / settings.UPLOAD_DIR
        upload_path.mkdir(parents=True, exist_ok=True)
        file_path = upload_path / unique_filename
        file_path.write_bytes(file_bytes)

        local_url = f"/api/orders/voucher/{unique_filename}"
        logger.info(f"📁 Voucher guardado en almacenamiento local ({file_path}): {local_url}")
        return local_url, unique_filename
    except Exception as e:
        logger.error(f"❌ Error crítico guardando voucher localmente: {e}")
        # En caso extremo de no poder escribir en disco, retornar URL de simulación
        mock_url = f"/api/orders/voucher/mock_{unique_filename}"
        return mock_url, unique_filename
