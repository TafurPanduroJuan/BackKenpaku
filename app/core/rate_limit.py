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


async def check_chat_rate_limit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not chat_rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes. Por favor espere un momento.",
        )


async def check_login_rate_limit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not login_rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Por favor intente más tarde.",
        )
