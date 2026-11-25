import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ChatLog
from app.services.cron_service import to_utc

logger = logging.getLogger(__name__)


def purge_old_chat_logs(
    db: Session,
    retention_days: Optional[int] = None,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Purga conversaciones del chat cuya última actividad (max timestamp) sea menor que cutoff.
    Se borra la conversación entera, nunca mensajes sueltos.
    """
    if retention_days is None:
        retention_days = settings.CHAT_LOG_RETENTION_DAYS

    if retention_days <= 0:
        return {
            "success": True,
            "retention_days": retention_days,
            "cutoff": None,
            "conversaciones_eliminadas": 0,
            "mensajes_eliminados": 0,
            "dry_run": dry_run,
            "detail": "Purga desactivada",
        }

    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = to_utc(now)

    cutoff = to_utc(now - timedelta(days=retention_days))

    if dry_run:
        eligible_query = (
            select(
                ChatLog.id_conversacion,
                func.count(ChatLog.id).label("num_mensajes"),
            )
            .group_by(ChatLog.id_conversacion)
            .having(func.max(ChatLog.timestamp) < cutoff)
        )
        rows = db.execute(eligible_query).all()
        conversaciones_elegibles = len(rows)
        mensajes_elegibles = sum(r.num_mensajes for r in rows)

        logger.info(
            "Purga de chat logs (dry_run): %d conversaciones y %d mensajes elegibles para purga (cutoff=%s)",
            conversaciones_elegibles,
            mensajes_elegibles,
            cutoff.isoformat(),
        )

        return {
            "success": True,
            "retention_days": retention_days,
            "cutoff": cutoff.isoformat(),
            "conversaciones_eliminadas": conversaciones_elegibles,
            "mensajes_eliminados": mensajes_elegibles,
            "dry_run": True,
        }

    batch_size = getattr(settings, "CHAT_LOG_PURGE_BATCH_SIZE", 1000)
    if batch_size <= 0:
        batch_size = 1000

    conversaciones_eliminadas = 0
    mensajes_eliminados = 0

    while True:
        batch_query = (
            select(ChatLog.id_conversacion)
            .group_by(ChatLog.id_conversacion)
            .having(func.max(ChatLog.timestamp) < cutoff)
            .limit(batch_size)
        )
        batch_convs = [r[0] for r in db.execute(batch_query).all()]
        if not batch_convs:
            break

        count_stmt = select(func.count(ChatLog.id)).where(ChatLog.id_conversacion.in_(batch_convs))
        batch_msgs_count = db.scalar(count_stmt) or 0

        del_stmt = (
            delete(ChatLog)
            .where(ChatLog.id_conversacion.in_(batch_convs))
            .execution_options(synchronize_session=False)
        )
        del_res = db.execute(del_stmt)
        db.commit()

        deleted_msgs = del_res.rowcount if del_res.rowcount and del_res.rowcount >= 0 else batch_msgs_count
        conversaciones_eliminadas += len(batch_convs)
        mensajes_eliminados += deleted_msgs

        logger.info(
            "Purga de chat logs lote: %d conversaciones y %d mensajes eliminados",
            len(batch_convs),
            deleted_msgs,
        )

    logger.info(
        "Purga de chat logs completada: %d conversaciones y %d mensajes eliminados en total (cutoff=%s)",
        conversaciones_eliminadas,
        mensajes_eliminados,
        cutoff.isoformat(),
    )

    return {
        "success": True,
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
        "conversaciones_eliminadas": conversaciones_eliminadas,
        "mensajes_eliminados": mensajes_eliminados,
        "dry_run": False,
    }
