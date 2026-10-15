from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["健康检查"])


@router.get("/health", response_model=HealthResponse, summary="检查服务是否可访问")
def check_health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """提供不依赖业务数据的存活检查，便于先验证前后端连接是否正常。"""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
