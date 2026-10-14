import pytest
from pydantic import ValidationError

from app.core.config import Settings

SEGUROS = dict(
    ENV="production",
    JWT_SECRET="a" * 40,
    CRON_SECRET="b" * 24,
    ADMIN_PASSWORD="Cl4ve-Segura-Prod-77",
)


def make(**cambios):
    return Settings(_env_file=None, **{**SEGUROS, **cambios})


def test_produccion_acepta_secretos_seguros():
    assert make().ENV == "production"


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("JWT_SECRET", "super-secret-jwt-key-change-in-production-min-32-chars"),
        ("JWT_SECRET", "corta"),
        ("CRON_SECRET", "kenpaku-cron-secret-key-2026"),
        ("CRON_SECRET", ""),
        ("ADMIN_PASSWORD", "AdminKenpaku2026!"),
        ("ADMIN_PASSWORD", ""),
    ],
)
def test_produccion_rechaza_secretos_inseguros(campo, valor):
    with pytest.raises(ValidationError):
        make(**{campo: valor})


def test_desarrollo_genera_secretos_efimeros_si_faltan():
    s = Settings(_env_file=None, ENV="development", JWT_SECRET="", CRON_SECRET="")
    assert len(s.JWT_SECRET) >= 32
    assert len(s.CRON_SECRET) >= 16