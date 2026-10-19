"""健康与文档测试，由 pytest 自动发现并通过正式应用工厂执行。

作用：固定存活契约、跨域来源边界、文档开关和配置覆盖的真实请求行为。
原因：这些能力由路由和中间件共同完成，函数级断言不足以证明应用集成正确；
配置文件读取显式隔离，环境变量覆盖由专门用例验证；健康检查不需要查询开发数据库。
"""

from collections.abc import Iterator  # 标注客户端夹具产出类型，提示测试资源需要按生命周期回收。

import pytest  # 导入测试框架，用夹具与参数化覆盖不同请求场景。
from fastapi.testclient import TestClient  # 调用完整应用链路，不需要额外启动网络服务器。

from app.core.config import Settings  # 使用正式配置模型，覆盖运行时相同的校验规则。
from app.main import create_app  # 通过正式应用工厂验证路由、中间件与生命周期。


@pytest.fixture  # 注册客户端夹具，让每个请求测试得到隔离应用。
def client() -> Iterator[TestClient]:  # 为本文件接口测试提供可自动关闭的客户端。
    """作用：隔离本机配置文件，确保健康接口的约定不随开发者个人配置变化。

    调用位置：本文件请求 client 参数的测试使用；pytest 负责准备与回收该生成器夹具。
    原因：健康、文档和跨域行为依赖应用配置及生命周期；独立显式设置并自动关闭客户端，可避免个人 .env、全局状态或未释放资源影响契约验证。
    """
    settings = Settings(  # 显式构造配置，避免个人设置改变健康接口约定。
        _env_file=None,  # 不读取 .env，防止私人数据库配置影响测试。
        app_name="FixFlow",  # 固定服务名，核对响应是否读取当前应用设置。
        app_version="0.1.0",  # 固定版本号，避免契约验证受个人环境影响。
        environment="development",  # 指定开发环境，核对返回的环境标识。
        docs_enabled=True,  # 开启文档，为文档契约验证准备入口。
        cors_origins=("http://localhost:5173", "http://127.0.0.1:5173"),  # 只允许两个本机前端来源，供后续分别验证。
    )  # 完成隔离设置，所有本用例请求使用同一配置。
    with TestClient(create_app(settings)) as test_client:  # 进入正式应用生命周期，覆盖启动和资源回收。
        yield test_client  # 将客户端交给测试，结束后自动退出上下文关闭应用。


def test_health_contract(client: TestClient) -> None:  # 验证健康接口完整契约，防止前端连接检查被改坏。
    """作用：锁定前端连接检查所依赖的字段，避免后续扩展时意外破坏约定。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：前端连接检查会读取这些字段；精确验证成功状态和完整正文，能在扩展接口时及时发现删改字段造成的兼容性问题。
    """
    response = client.get("/api/v1/health")  # 请求正式健康路由，覆盖路径注册与处理逻辑。
    assert response.status_code == 200  # 正常存活时应返回成功状态。
    assert response.json() == {  # 精确核对完整响应，及时发现字段删改。
        "status": "ok",  # 固定存活标志，前端据此识别服务响应正常。
        "service": "FixFlow",  # 服务名必须来自当前测试配置。
        "version": "0.1.0",  # 版本号必须来自当前测试配置。
        "environment": "development",  # 环境标识不能被其他应用或本机设置覆盖。
    }  # 完整响应契约包含四个字段，额外变更会提示重新评估。


@pytest.mark.parametrize(  # 将跨域检查展开为两项独立用例。
    "origin", ["http://localhost:5173", "http://127.0.0.1:5173"]  # 分别覆盖 localhost 与回环地址两种前端入口。
)  # 完成参数化设置，确保两种来源都执行后面的断言。
def test_local_frontend_origin_allowed(client: TestClient, origin: str) -> None:  # 验证合法来源的预检与实际响应都携带跨域许可。
    """作用：同时兼容两种本机访问方式，避免前端换主机名后被浏览器阻止。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：本机前端可能用 localhost 或回环地址访问，浏览器认为它们是不同来源；预检和实际读取都检查许可头才能证明两种入口可联调。
    """
    response = client.options(  # 模拟浏览器发起的预检，覆盖跨域中间件。
        "/api/v1/health",  # 对真实健康路由预检，避免使用不存在的测试路径。
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},  # 提供来源和预期请求方法，让中间件执行真实判定。
    )  # 取得预检响应，随后检查状态码和许可头。
    assert response.status_code == 200  # 白名单内来源应被允许通过预检。
    assert response.headers["access-control-allow-origin"] == origin  # 许可头必须匹配来源，不能扩大成允许所有网页。
    health_response = client.get("/api/v1/health", headers={"Origin": origin})  # 继续发送真实读取请求，防止仅预检正确。
    assert health_response.headers["access-control-allow-origin"] == origin  # 实际响应也必须允许相同来源，否则浏览器无法读取结果。


def test_unknown_origin_rejected(client: TestClient) -> None:  # 验证陌生网页不能获得跨域读取许可。
    """作用：检查来源白名单，避免为了本地联调而放开所有网页的跨域访问。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：开发联调不能以放开所有来源为代价；陌生来源样本核对预检失败和许可头缺失，防止中间件配置意外扩大网页访问范围。
    """
    response = client.options(  # 构造不受信来源的浏览器预检请求。
        "/api/v1/health",  # 沿用同一健康路由，排除路径差异影响。
        headers={  # 准备预检必须的头字段，不绕开中间件。
            "Origin": "https://untrusted.example",  # 使用白名单外域名，固定应拒绝的来源。
            "Access-Control-Request-Method": "GET",  # 声明读取方法，使拒绝原因来自来源限制。
        },  # 完成不受信请求头，其他条件与合法预检相同。
    )  # 发送预检并取得实际拒绝结果。
    assert response.status_code == 400  # 陌生来源的预检应返回失败状态。
    assert "access-control-allow-origin" not in response.headers  # 拒绝响应不得携带许可头，避免浏览器误判为允许访问。


def test_generated_documentation(client: TestClient) -> None:  # 验证文档描述与真实接口的路径、模型一致。
    """作用：确保开发者能从文档看到真实健康接口及其返回结构。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：文档网页可打开并不代表接口结构正确；核对机器结构中的路径与必填字段，才能让调用方按文档获得与实际响应一致的约定。
    """
    assert client.get("/docs").status_code == 200  # 交互文档页面在开发配置下应正常存在。
    assert client.get("/redoc").status_code == 200  # 备用接口文档也应存在，防止只注册了一个入口。
    response = client.get("/openapi.json")  # 读取机器可读的接口结构，核对文档背后的契约。
    assert response.status_code == 200  # 结构文件应正常响应，不能只有文档页面外壳。
    schema = response.json()  # 解析接口结构，供后续检查标题与模型。
    assert schema["info"]["title"] == "FixFlow"  # 文档标题应使用本应用名称。
    assert "/api/v1/health" in schema["paths"]  # 健康路由应出现在文档路径中，方便联调发现。
    assert schema["components"]["schemas"]["HealthResponse"]["required"] == [  # 核对响应模型必填字段，防止必要字段被误改为可选。
        "status", "service", "version", "environment"  # 固定前端依赖的状态、服务、版本和环境四项。
    ]  # 完成必填列表核对，接口模型变更必须明确评估。


def test_documentation_can_be_disabled() -> None:  # 验证关闭文档时所有入口一起关闭，正常接口仍可用。
    """作用：验证文档开关同时关闭网页和结构描述，方便部署时统一控制。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：部署可能要求统一关闭接口说明；只关闭网页仍可能留下结构文件，且开关不能误伤健康路由，因此要逐一验证所有入口和正常接口。
    """
    settings = Settings(_env_file=None, docs_enabled=False)  # 隔离 .env 并关闭文档，确保开关效果可重复验证。
    with TestClient(create_app(settings)) as client:  # 用关闭文档的配置创建应用，覆盖路由注册分支。
        for path in ("/docs", "/redoc", "/openapi.json"):  # 逐一检查两种页面和结构文件入口。
            assert client.get(path).status_code == 404  # 每个文档入口都应不存在，不能只隐藏页面。
        assert client.get("/api/v1/health").status_code == 200  # 文档开关不能影响正常存活检查。


def test_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:  # 验证环境变量覆盖默认配置，并贯通到实际响应。
    """作用：确认部署可以通过环境变量调整配置，且接口使用同一份配置。

    调用位置：由 pytest 自动发现执行，参数中的测试夹具在每次执行前准备隔离环境。
    原因：部署通常通过环境变量传入环境和来源设置；不仅检查配置模型，还检查真实响应使用新值，才能证明覆盖设置贯通到了请求处理。
    """
    monkeypatch.setenv("FIXFLOW_ENVIRONMENT", "test")  # 临时设置运行环境，测试结束后由夹具恢复。
    monkeypatch.setenv("FIXFLOW_CORS_ORIGINS", '["http://localhost:6000"]')  # 用结构化来源列表验证环境变量解析。
    settings = Settings(_env_file=None)  # 不读 .env，让本项仅证明环境变量生效。
    assert settings.environment == "test"  # 环境必须采用变量值，不能一直返回默认值。
    assert settings.cors_origins == ("http://localhost:6000",)  # 来源列表应转换为约定序列类型。
    with TestClient(create_app(settings)) as client:  # 用新设置创建应用，验证配置与请求处理相连。
        assert client.get("/api/v1/health").json()["environment"] == "test"  # 健康响应必须显示新环境，证明不只是模型解析成功。
