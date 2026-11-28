# MemeRetrieve 产品使用与部署

## English overview

Open `/web/`, sign in, and choose **Local only** to search the reference corpus
and indexed saved GIFs. If the target is missing, choose **Continue online**
and provide a description. Online search requires operator-configured vision
and DeepSeek credentials. Review and play a candidate before using **Confirm
and save**; wait for its index status to become ready before expecting offline
reuse.

The product stack uses Python 3.11, Docker Compose, PostgreSQL 16, an API, a
separate worker, persistent media/model volumes, and an isolated public-media
fetch service. The detailed PowerShell setup and upgrade commands below are
maintained in Chinese. See the [W13 delivery report](../submissions/week13/README.md)
for the verified workflow and its limitations.

打开 `http://127.0.0.1:8000/web/`，点击 **Enter workspace**。首次使用点 **Register** 选择用户名和至少八位的密码，之后用 **Sign in** 打开自己的收藏。右上角的 **Sign out** 结束当前会话。每个账号的收藏、导入和搜索历史存放在独立工作空间。

## 用网页找回和收藏 GIF | Recover and save GIFs in the web app

选择、拖入或粘贴 PNG、JPEG 或 WebP 截图后，可点 **Crop screenshot** 框选表情并确认；也可以保留整图。确认后的同一张图用于本地检索和后续联网搜索。选择 **Local only** 搜索参考库和你已索引的收藏。目标不在结果里时，点 **Continue online** 并描述画面、动作或记得的来源。联网模式需要运营者配置识图模型和 DeepSeek。结果页的 **Search activity** 展示真实调用数和查询计划，任务结束后可查看实际执行的查询及返回的来源数。

在结果中播放动画。在已完成的搜索结果上点 **Add to My Library** 可收藏静态图或动图原件。点 **View in My Library** 即可查看刚收藏的图片。索引完成后可用本地搜索找回。本地参考结果可点 **This is the one** 后下载。通过 **My Library** 管理、下载或批量导入原始 GIF，也可以换一帧重新本地检索。下载按钮提供原件。搜索结果与 **My Library** 中的静态图、动图都可点 **Share**。文件就绪后点 **Open share menu**，在系统分享面板选择接收应用。浏览器不支持该格式的文件分享时，可下载原件发送。

Select, drop, or paste a PNG, JPEG, or WebP screenshot. Choose **Crop
screenshot** to select and confirm the meme region, or keep the full image.
The same confirmed image is used for local search and any subsequent online
search. Choose **Local only** to search the reference corpus and indexed saved GIFs. If the target is missing,
choose **Continue online** and describe the scene, action, or known source.
Online search requires operator-configured vision and DeepSeek credentials.
**Search activity** shows the actual calls and query plan after the job ends.

Play an animated result before review. For an online candidate, choose
**Confirm and save** and wait for indexing to finish. A local reference result
can be downloaded with **This is the one**. **My GIF Library** supports
managing, downloading, and batch-importing original GIFs, and searching again
from another frame. Downloads contain the original media. **Share GIF** opens
the system share sheet where supported by the browser and device.

## 首次启动 Docker 版本 | First Docker setup

使用 Docker Compose v2 和 Python 3.11。从仓库根目录运行下列 PowerShell 命令，准备公开参考库和固定版本 CLIP 模型。后续启动可继续使用同一份文件。

Use Docker Compose v2 and Python 3.11. From the repository root, prepare the
reference corpus and pinned CLIP model with the PowerShell commands below.
These files are also used on subsequent starts.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe scripts/prepare_demo.py
.\.venv\Scripts\python.exe scripts/download_model.py
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在新安装的 `.env` 中把 `POSTGRES_PASSWORD` 设为自己的随机字母数字密码。已有 `.env` 继续使用原文件并核对设置。账号和私人库在产品 Compose 配置里默认启用。已有配置若显式将这些选项设为 `false`，请改为 `ACCOUNT_LOGIN_ENABLED=true` 和 `PRIVATE_LIBRARY_ENABLED=true`。在线使用另按供应商指南配置。首次体验本地使用只需数据库和缓存模型。[供应商配置](hkust-deepseek-execution.md)

For a new `.env`, set `POSTGRES_PASSWORD` to a private random alphanumeric
value. Keep an existing `.env` and verify its settings rather than replacing
it. Account login and the private library are enabled by default in the
product Compose configuration. If an existing configuration explicitly sets
either option to `false`, set `ACCOUNT_LOGIN_ENABLED=true` and
`PRIVATE_LIBRARY_ENABLED=true`. Configure providers separately for online
search. Local-only search needs the database and cached model; see the
[provider guide](hkust-deepseek-execution.md).

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

For routine startup, run `docker compose @product up -d --wait`; use
`docker compose @product stop` to stop without deleting persistent volumes.
Follow API and worker logs during the first save or search with
`docker compose @product logs -f api worker`. The `vector_backend` and
`reference_vector_backend` log fields identify the search backend used for
private and public assets. Ready local assets remain searchable when online
providers are unavailable.

## 升级已有 PostgreSQL 16 安装 | Upgrade an existing PostgreSQL 16 deployment

沿用现有 Compose 项目名。停写入后，同时备份原数据库和媒体卷，保留旧数据库卷。pgvector Compose 配置用独立的 `pgvector_data` 卷。将旧 PostgreSQL 的数据逻辑导入新的空数据库，以保留所有账户 schema、资产 ID 和回执。下列导入命令适用于旧版 Compose 数据库，使用宿主部署时用对应的 `pg_dump` 和 `pg_restore`。

Keep the existing Compose project name. Stop writes, back up PostgreSQL and
the media volume together, and retain the old database volume. The pgvector
Compose profile uses a separate `pgvector_data` volume. Restore the old
PostgreSQL data logically into the new empty database to preserve account
schemas, asset IDs, and receipts. The commands below apply to the previous
Compose database; use the corresponding host `pg_dump` and `pg_restore`
commands for a native deployment.

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

Check the registered workspaces with the command below. Backfill `public`
first, then run the saved-index backfill separately for each `acct_...`
workspace, replacing the example workspace argument with its actual name.

```powershell
docker compose @product run --rm --no-deps worker python -m services.retrieval.saved_index --workspace public
docker compose @product up -d --wait
```

回填从已经验证的收藏 NPZ 读取帧向量，并核对原件和索引版本。检查输出中的 `ready` 与 `mirrored` 是否一致。原单用户库如果尚未绑定账号，用 `docker compose @product exec -T api python -m services.common.accounts` 取一次性设置码，打开 `/web/sign-in#setup=<设置码>` 并用 **Register** 绑定旧库。已有账号直接登录。

Backfill reads frame vectors from validated saved NPZ files and checks the
original media and index version. Confirm that the reported `ready` and
`mirrored` counts are consistent. If the legacy single-user library has not
been associated with an account, obtain a one-time setup code with the command
below, then open `/web/sign-in#setup=<code>` and use **Register** to bind the
existing library. Existing users should sign in normally.

迁移后用旧账号核对收藏和原件，再收藏一张新 GIF，重启后使用另一帧做本地检索。需要强制使用 NPZ 时在 `.env` 设置 `VECTOR_BACKEND=npz`，然后运行 `docker compose @product up -d --force-recreate worker`。继续使用同一个 Compose 项目和媒体卷。

After migration, sign in with an existing account and verify saved assets and
original files. Save one new GIF, restart the services, and search using a
different frame. To force the NPZ backend, set `VECTOR_BACKEND=npz` in `.env`
and recreate the worker with the command below. Keep the same Compose project
and media volume.
