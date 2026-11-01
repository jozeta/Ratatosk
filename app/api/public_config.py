from fastapi import APIRouter

from app.core.dynamic_settings import get_settings
from app.schemas.settings import public_config as build_public_config

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def public_config():
    """Non-sensitive subset of policy for the frontend; the field list lives
    next to the settings schema (ARCH-004)."""
    return build_public_config(get_settings())
