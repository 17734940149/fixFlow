# FixFlow 后端

Python 3.14、FastAPI、PostgreSQL。已提供健康检查、数据库就绪检查、登录、当前身份查询和退出接口。前端已接入真实认证；问答、资料管理、历史记录与个人资料编辑仍为本机演示。

## 环境准备

- Python：`>=3.14,<3.15`。
- PostgreSQL：18.x；先创建数据库和专用连接账号。
- 以下命令在 `backend/` 目录执行；已有虚拟环境时跳过创建步骤。

```powershell
python -m venv .venv # 仅首次创建项目虚拟环境。
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt # 安装开发及测试依赖；正式运行使用 requirements.txt。
```

## 配置与数据库初始化

仅在 `.env` 不存在时复制模板：

```powershell
Copy-Item .env.example .env # 首次复制配置，已有本机配置时不要覆盖。
```

在本机 `.env` 中设置 `FIXFLOW_DATABASE_URL`，其他可配置项见 [.env.example](.env.example)。真实密码及连接信息不要提交到 Git，修改配置后重启服务。

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head # 执行数据库结构迁移，普通启动不会自动建表。
.\.venv\Scripts\python.exe -m app.cli check-db # 检查连接和必要表，正常输出 database: ready。
.\.venv\Scripts\python.exe -m app.cli create-user --account admin --display-name 管理员 --role admin # 交互创建网站管理员，密码至少 12 个字符。
```

`admin` 是示例应用账号名，已存在时使用已有账号或选择其他名称；普通用户使用 `--role user`。没有默认网站密码，数据库连接账号不能用于网页登录。

## 启动与接口

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8100 # 本机开发启动，终端需保持运行。
```

| 方法 | 地址 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/health` | 服务存活 |
| GET | `/api/v1/ready` | 数据库就绪 |
| POST | `/api/v1/auth/login` | 账号密码登录 |
| GET | `/api/v1/auth/me` | 当前身份 |
| POST | `/api/v1/auth/logout` | 退出当前会话 |

本机 [接口文档](http://127.0.0.1:8100/docs)、[接口结构描述](http://127.0.0.1:8100/openapi.json)。文档入口可通过 `FIXFLOW_DOCS_ENABLED` 配置关闭。前端启动见 [前端说明](../frontend/README.md)。

## 验证与维护

```powershell
.\.venv\Scripts\python.exe -m pytest # 运行测试；真实 PostgreSQL 测试需显式指定独立测试库。
.\.venv\Scripts\python.exe -m pip check # 检查已安装依赖的版本关系。
.\.venv\Scripts\python.exe -m app.cli cleanup-sessions # 清理已到期的登录会话。
```

## Git 范围

仓库仅保留 `frontend/`、`backend/`，排除本机配置、依赖和生成产物。新克隆后在仓库根目录启用本地检查：

```powershell
git config --local core.hooksPath backend/.githooks # 为当前仓库启用提交与推送范围检查。
```

## 文档入口

学习资料统一保存在项目根目录 `docs/`，该目录按当前规则不随 Git 上传。

- [后端基础学习笔记](../docs/后端基础学习笔记-20261020.md)
- [数据库、账号与容量估算](../docs/03-数据库接入与真实登录-20261016.md)
- [后端逐行注释与请求流程](../docs/04-后端逐行注释与请求流程-20261016.md)
- [前后端真实登录联调](../docs/07-前后端真实登录联调与身份恢复-20261019.md)
- [Git 提交范围与回退](../docs/02-Git提交范围与回退-20261020.md)
