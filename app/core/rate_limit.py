import time
from collections import defaultdict

from fastapi import HTTPException, Request, status


class IPRateLimiter:
    """Rate limiter en memoria por IP del cliente."""

    def __init__(self, requests_per_minute: int = 15, window_seconds: int = 60):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        # Filtrar solicitudes más antiguas que la ventana de tiempo
        self.requests[ip] = [
            t for t in self.requests[ip] if now - t < self.window_seconds
        ]
        if len(self.requests[ip]) >= self.requests_per_minute:
            return False
        self.requests[ip].append(now)
        return True


chat_rate_limiter = IPRateLimiter(requests_per_minute=20, window_seconds=60)
login_rate_limiter = IPRateLimiter(requests_per_minute=5, window_seconds=60)
tracking_rate_limiter = IPRateLimiter(requests_per_minute=25, window_seconds=60)


def get_real_client_ip(request: Request) -> str:
    """Extrae la IP real del visitante considerando cabeceras de proxy inverso (Render / CDN)."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # La primera IP de la lista es la del cliente original
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


async def check_chat_rate_limit(request: Request):
    client_ip = get_real_client_ip(request)
    if not chat_rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes. Por favor espere un momento.",
        )


async def check_login_rate_limit(request: Request):
    client_ip = get_real_client_ip(request)
    if not login_rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Por favor intente más tarde.",
        )


async def check_tracking_rate_limit(request: Request):
    client_ip = get_real_client_ip(request)
    if not tracking_rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas consultas de seguimiento. Por favor espere un momento.",
        )
