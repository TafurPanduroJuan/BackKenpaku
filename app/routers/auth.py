from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.rate_limit import check_login_rate_limit
from app.core.security import create_access_token, decode_access_token, verify_password
from app.db.models import User, UserRolEnum
from app.db.session import get_db
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["Auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_admin_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Inyección de dependencia para autenticar y autorizar a usuarios administradores mediante JWT."""
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "Token no válido o expirado.", "code": "UNAUTHORIZED"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_identifier = payload.get("sub")
    user = (
        db.query(User)
        .filter(
            (User.email == user_identifier),
            User.activo == True,
            User.rol == UserRolEnum.admin,
        )
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "Usuario no autorizado o inactivo.", "code": "UNAUTHORIZED"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(check_login_rate_limit)],
)
def login(login_in: LoginRequest, db: Session = Depends(get_db)):
    """Endpoint de autenticación para administradores."""
    user = (
        db.query(User)
        .filter(User.email == login_in.email, User.activo == True)
        .first()
    )

    if not user or not verify_password(login_in.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "Credenciales incorrectas.", "code": "UNAUTHORIZED"},
        )

    access_token = create_access_token(subject=user.email)
    return TokenResponse(access_token=access_token, token_type="bearer")
