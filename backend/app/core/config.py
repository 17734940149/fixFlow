from pathlib import Path
from typing import Literal

from fastapi import Request
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """统一读取环境配置，避免开发和部署时直接修改业务代码。"""

    model_config = SettingsConfigDict(
        env_prefix="FIXFLOW_",
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "FixFlow"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    docs_enabled: bool = True
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )


def get_settings(request: Request) -> Settings:
    """使用当前应用的配置，避免多个测试应用之间共享可变的全局配置。"""
    return request.app.state.settings
