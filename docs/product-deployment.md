# MemeRetrieve 产品使用与部署

打开 `http://127.0.0.1:8000/web/`，在主题首页点 **Enter workspace**。首次使用点 **Register** 选择用户名和至少八位的密码，之后用 **Sign in** 登录。工作台导航里的 **Sign out** 结束当前会话，点击 MemeRetrieve 标识可回到主题首页。每个账号的收藏、导入和搜索历史存放在独立工作空间。

## 用网页找回和收藏表情包

上传裁好的 PNG、JPEG 或 WebP 截图。选择 **Local only** 搜索参考库和你已索引的收藏。目标不在结果里时，点 **Continue online** 并描述画面、动作或记得的来源。联网模式需要运营者配置识图模型和 DeepSeek。

在结果中播放动画。在已完成的搜索结果上点 **Add to My Library** 可收藏静态图或动图原件。点 **View in My Library** 即可查看刚收藏的图片。索引完成后可用本地搜索找回。本地参考结果可点 **This is the one** 后下载。通过 **My Library** 管理、下载或批量导入原始 GIF，也可以换一帧重新本地检索。下载按钮提供原件。搜索结果与 **My Library** 中的静态图、动图都可点 **Share**。文件就绪后点 **Open share menu**，在系统分享面板选择接收应用。浏览器不支持该格式的文件分享时，可下载原件发送。

## 首次启动 Docker 版本

使用 Docker Compose v2 和 Python 3.11。从仓库根目录运行下列 PowerShell 命令，准备公开参考库和固定版本 CLIP 模型。后续启动可继续使用同一份文件。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe scripts/prepare_demo.py
.\.venv\Scripts\python.exe scripts/download_model.py
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在新安装的 `.env` 中把 `POSTGRES_PASSWORD` 设为自己的随机字母数字密码。已有 `.env` 继续使用原文件并核对设置。账号和私人库在产品 Compose 配置里默认启用。已有配置若显式将这些选项设为 `false`，请改为 `ACCOUNT_LOGIN_ENABLED=true` 和 `PRIVATE_LIBRARY_ENABLED=true`。在线使用另按供应商指南配置。首次体验本地使用只需数据库和缓存模型。[供应商配置](hkust-deepseek-execution.md)

```powershell
$product = @('-f', 'compose.yaml', '-f', 'compose.local-model.yaml', '-f', 'compose.pgvector.yaml')
docker compose @product up -d --wait db
docker compose @product build api worker media-fetch
docker compose @product run --rm --no-deps api alembic upgrade head
docker compose @product run --rm --no-deps api python -m services.retrieval.vector_store provision
docker compose @product run --rm --no-deps api python -m services.common.reference_assets /data/reference/manifest.json
docker compose @product run --rm --no-deps worker python -m services.retrieval.engine index
docker compose @product up -d --wait
docker compose @product ps
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

先导入参考清单，再让用户注册。API 负责账号、会话、网页、任务和下载。worker 处理 CLIP、联网搜索、收藏索引和离线检索。PostgreSQL 16 保存账号、任务、收藏状态和 pgvector 帧向量，原件和 NPZ 收藏索引保存在持久媒体卷。隔离的抓取服务负责访问公开媒体。远程部署时，以同一 HTTPS 域名提供网页和 API，并让代理转发 HTTPS 协议。

日常启动用 `docker compose @product up -d --wait`。停止用 `docker compose @product stop`。初次保存或检索时可用 `docker compose @product logs -f api worker` 看任务进度。本地任务日志中的 `vector_backend` 和 `reference_vector_backend` 分别记录私人收藏和公共参考检索使用的路径。联网服务不可用时仍可通过 **Local only** 查找已就绪的收藏。

## 升级已有 PostgreSQL 16 安装

沿用现有 Compose 项目名。停写入后，同时备份原数据库和媒体卷，保留旧数据库卷。pgvector Compose 配置用独立的 `pgvector_data` 卷。将旧 PostgreSQL 的数据逻辑导入新的空数据库，以保留所有账户 schema、资产 ID 和回执。下列导入命令适用于旧版 Compose 数据库，使用宿主部署时用对应的 `pg_dump` 和 `pg_restore`。

```powershell
New-Item -ItemType Directory -Force .cache
docker compose stop worker api
docker compose exec -T db pg_dump -Fc -U postgres -d maie6000c -f /tmp/memeretrieve.dump
docker compose cp db:/tmp/memeretrieve.dump ./.cache/memeretrieve.dump
docker compose @product up -d --wait db
docker compose @product cp ./.cache/memeretrieve.dump db:/tmp/memeretrieve.dump
docker compose @product exec -T db pg_restore --exit-on-error --no-owner -U postgres -d maie6000c /tmp/memeretrieve.dump
docker compose @product run --rm --no-deps api alembic upgrade head
docker compose @product run --rm --no-deps api python -m services.retrieval.vector_store provision
docker compose @product run --rm --no-deps api python -m services.common.reference_assets /data/reference/manifest.json
docker compose @product run --rm --no-deps worker python -m services.retrieval.engine index
```

用 `docker compose @product exec -T db psql -U postgres -d maie6000c -c "SELECT workspace FROM library_accounts ORDER BY workspace"` 核对工作空间。先回填 `public`，再对每个 `acct_...` 空间分别运行同一条命令。把示例最后一个参数 `public` 替换为该空间的真实名称。

```powershell
docker compose @product run --rm --no-deps worker python -m services.retrieval.saved_index --workspace public
docker compose @product up -d --wait
```

回填从已经验证的收藏 NPZ 读取帧向量，并核对原件和索引版本。检查输出中的 `ready` 与 `mirrored` 是否一致。原单用户库如果尚未绑定账号，用 `docker compose @product exec -T api python -m services.common.accounts` 取一次性设置码，打开 `/web/sign-in#setup=<设置码>` 并用 **Register** 绑定旧库。已有账号直接登录。

迁移后用旧账号核对收藏和原件，再收藏一张新 GIF，重启后使用另一帧做本地检索。需要强制使用 NPZ 时在 `.env` 设置 `VECTOR_BACKEND=npz`，然后运行 `docker compose @product up -d --force-recreate worker`。继续使用同一个 Compose 项目和媒体卷。
