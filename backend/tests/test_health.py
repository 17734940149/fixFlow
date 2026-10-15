from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """隔离本机配置文件，确保健康接口的约定不随开发者个人配置变化。"""
    settings = Settings(
        _env_file=None,
        app_name="FixFlow",
        app_version="0.1.0",
        environment="development",
        docs_enabled=True,
        cors_origins=("http://localhost:5173", "http://127.0.0.1:5173"),
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_health_contract(client: TestClient) -> None:
    """锁定前端连接检查所依赖的字段，避免后续扩展时意外破坏约定。"""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "FixFlow",
        "version": "0.1.0",
        "environment": "development",
    }


@pytest.mark.parametrize(
    "origin", ["http://localhost:5173", "http://127.0.0.1:5173"]
)
def test_local_frontend_origin_allowed(client: TestClient, origin: str) -> None:
    """同时兼容两种本机访问方式，避免前端换主机名后被浏览器阻止。"""
    response = client.options(
        "/api/v1/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    health_response = client.get("/api/v1/health", headers={"Origin": origin})
    assert health_response.headers["access-control-allow-origin"] == origin


def test_unknown_origin_rejected(client: TestClient) -> None:
    """检查来源白名单，避免为了本地联调而放开所有网页的跨域访问。"""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_generated_documentation(client: TestClient) -> None:
    """确保开发者能从文档看到真实健康接口及其返回结构。"""
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "FixFlow"
    assert "/api/v1/health" in schema["paths"]
    assert schema["components"]["schemas"]["HealthResponse"]["required"] == [
        "status", "service", "version", "environment"
    ]


def test_documentation_can_be_disabled() -> None:
    """验证文档开关同时关闭网页和结构描述，方便部署时统一控制。"""
    settings = Settings(_env_file=None, docs_enabled=False)
    with TestClient(create_app(settings)) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
        assert client.get("/api/v1/health").status_code == 200


def test_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """确认部署可以通过环境变量调整配置，且接口使用同一份配置。"""
    monkeypatch.setenv("FIXFLOW_ENVIRONMENT", "test")
    monkeypatch.setenv("FIXFLOW_CORS_ORIGINS", '["http://localhost:6000"]')
    settings = Settings(_env_file=None)
    assert settings.environment == "test"
    assert settings.cors_origins == ("http://localhost:6000",)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health").json()["environment"] == "test"
