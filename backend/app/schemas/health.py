from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """明确健康检查返回的字段，让前端和接口文档保持一致。"""

    status: Literal["ok"]
    service: str
    version: str
    environment: Literal["development", "test", "production"]
