# 后端开发手册

[English](../backend-guide.md) · [技术文档首页](README.zh-CN.md)

W07 及期中后集成的后端负责人为 Haoxuan Jiang。此手册保留当时的后端契约、测试与兼容路径，并标明当前产品的入口。W04 的架构属于早期方案。网页由 Zirui 对接，检索与索引适配器由 YuanJian 对接。[团队计划](../week07-plan.md) · [当前系统与验收](README.zh-CN.md)

## 实现范围和服务边界

后端提供 multipart 上传、PostgreSQL 迁移、持久化任务、原子领取、幂等重试与审阅、GIF 目录导入校验、共享存储、临时媒体过期，以及分开运行的 API 与 worker。期中后加入与原请求关联的联网任务、agent 执行轨迹、带来源信息的临时候选、独立的收藏资产表和持久化建索引队列。收藏写入 `saved_assets`，固定参考目录由运营者单独导入。

迁移 `20261109_0003` 在 PostgreSQL 中原地更改既有表以保留指向它们的外键。只有在 SQLite 需要时 Alembic 才按批次重建表。PostgreSQL CI 对真实数据库执行升级、降级并核对 ORM 元数据。[数据库与向量索引](../database-and-vector-search.md)

传统 worker 在有超时限制的子进程内调用 `services.retrieval.search(image_path, top_k=3)` 与 `services.search_agent`。旧版联网流程的 `services.retrieval.prepare_candidates(image_path, sources, work_dir, budget)` 对媒体校验并返回多帧 GIF。缺失适配器时任务记录 `candidate_processor_unavailable`。发现的网页仍是来源线索。当前 `meme50-v2` 另行发布通过实际下载和解码的静态及动态结果。[候选适配器](../../services/retrieval/candidates.py) · [当前搜索流程](../../services/search_agent/meme_pipeline.py)

`services.retrieval.index_saved_asset(asset_id)` 校验原件并原子发布新索引。worker 接受索引版本字符串或含 `index_version` 的对象。新索引验证失败时保留之前的索引文件，资产可显示 `index_status=failed` 并允许重试。建索引成功后本地检索需同时支持已就绪的收藏 ID 和固定参考 ID，worker 解析所属模型并核验原件摘要与帧数。注入确定性匹配的测试可验证后端契约。真实模型、外部调用及命中率分别查看对应运行记录。[收藏索引](../../services/retrieval/saved_index.py) · [浏览器验收记录](../../submissions/week13/browser-release-verification.json)

## 运行后端

从仓库根目录执行以下 PowerShell 命令可启动基础开发配置。首次复制 `.env.example` 后，先把 `.env` 里的 `POSTGRES_PASSWORD` 设为自己的随机十六进制密码；已有环境文件应保留。Compose 会拒绝空密码。带账号、CLIP 模型和 pgvector 的完整产品请按[产品部署指南](../product-deployment.md)启动。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 首次部署先在 .env 设置 POSTGRES_PASSWORD
docker compose up --build -d
Invoke-RestMethod http://localhost:8000/health/ready
docker compose logs --tail 30 worker
```

API 交互文档位于 `http://localhost:8000/docs`。当前基础组合包括 PostgreSQL、API、一个搜索 worker 和 `media-fetch`。旧课程 starter 可通过 `docker compose --profile starter up --build -d` 增加 `ai` 及 `starter-worker`。两个 worker 各自利用 PostgreSQL advisory lock 防止第二个实例同时执行启动恢复。被中断的 starter 分流任务会回到 `pending`，对应 case 回到 `queued`。收到 SIGTERM 后，worker 等待受限操作完成并更新数据库。starter 的 AI 请求超时取自 `WORKER_REQUEST_TIMEOUT_SECONDS`，默认关闭宽限期 `STARTER_WORKER_STOP_GRACE_PERIOD` 为 30 秒。如果调大超时，应给数据库写入留出额外时间。

搜索 worker 的 `SEARCH_WORKER_STOP_GRACE_PERIOD` 默认为 330 秒，覆盖默认 300 秒的收藏建索引及有界联网和本地检索。若提高任何超时，宽限期也要高于耗时最长的操作并允许校验和提交。Compose 服务使用 `unless-stopped`，手动停止的服务保持停止，意外退出的容器进程会重启。Docker 的 `json-file` 日志每个服务容器最多保留三个 10 MiB 文件。[服务定义](../../compose.yaml)

API、两个 worker、AI 服务和 Prometheus 取消额外 Linux capabilities、禁用提权。应用服务使用非特权 UID 10001，镜像在构建时准备好可写的媒体和模型缓存目录。数据库保留官方入口初始化数据目录所需的权限。密码仅使用 URI 无需转义的字符（字母、数字及 `-`、`.`、`_`、`~`）；API 和 worker 从连接 URL 读取数据库凭据。已有数据卷需要先修改 PostgreSQL 角色密码，再同步应用配置。修改 env 本身只影响注入的新配置。每个容器仅接收其所需配置。

基础配置里的 API、AI、Prometheus 和数据库主机端口默认绑定回环地址。旧单设备 LAN 接入可在 `.env` 设置私人 `DEVICE_TOKEN` 和 `API_BIND_HOST=0.0.0.0`，搜索、候选、审阅和重试请求带 `Authorization: Bearer <token>`。该模式下健康端点和旧 starter 路由可匿名访问，应使用主机防火墙限定 LAN 来源。AI 与 Prometheus 缺少服务内鉴权，保留 `AI_BIND_HOST`、`PROMETHEUS_BIND_HOST` 和数据库端口的回环绑定。当前账号部署使用服务端会话选择工作空间；本机公测另用邀请码，关闭联网任务。[账号与公测配置](../public-beta.md)

## 共享文件、任务与保留期

| 数据 | Compose 位置 | 生命周期 |
| --- | --- | --- |
| 请求、任务、结果、审阅、目录 | 基础版 PostgreSQL `postgres_data` 卷；pgvector 配置使用独立的 `pgvector_data` | 容器重建后保留 |
| 截图与候选媒体传输副本 | `task_media`，挂载到 `/data/media` | 任务终止后默认七天进入清理 |
| 收藏 GIF 与收藏 NPZ | 同一媒体卷中资产所属工作空间的目录 | 跨任务和重启保留 |
| 参考 GIF 与清单 | 主机 `data/reference`，API 和 worker 只读挂载到 `/data/reference` | 持久保留 |
| 模型缓存 | `model_cache`，挂载到 `/data/models` | 持久保留 |
| Prometheus 时序数据 | `prometheus_data`，挂载到 `/prometheus` | 容器重建后保留，保留上限 15 天或 2 GiB |

`docker compose down` 保留命名卷。`down -v` 会删除该 Compose 项目的数据库、媒体、模型缓存及使用中的 Prometheus 卷。挂载在宿主机目录中的参考文件独立保留。语料位于其他目录时，启动前设置 `REFERENCE_HOST_PATH`。发布文件后再导入清单。检索代码使用配置的共享路径。`data/`、本地截图、批量动图、模型权重、缓存和环境文件应留在仓库与构建上下文之外。

本地上传接口对解码的 JPEG、PNG、WebP 校验大小与尺寸，默认上限 10 MiB、2,000 万像素。截图原子写入，随后将请求和任务在同一事务提交，再返回 `202`。数据库失败会清理尚未提交的输入。意外中断可能遗留孤立文件，启动时和每小时的清理会删除超过一天且没有引用的文件。若清理失败，记录日志、保留原始数据库或存储错误供诊断，等下一轮清理处理。非本机接入应在反向代理限制请求体大小，因为 multipart 解析可能先于路由校验而产生临时文件。

worker 用 `FOR UPDATE SKIP LOCKED` 领取，提交 `running` 后才在领取事务之外执行推理和文件操作；候选与最终状态一起提交。本地检索子进程默认超时 120 秒。W07 检索路径最多保存三个多帧 GIF，每个候选都要与目录 SHA 一致并可完整解码。该路径限制 25 MiB、每帧 2,000 万像素、最多 1,000 帧、解码总量一亿像素。相似度是有限的排序分值。PostgreSQL 约束同时拒绝无效分值、不相符的状态与时间戳，以及早于开始时间的结束时间。请求与 attempt、任务与 rank 的组合唯一索引也覆盖对应查询前缀。

启动时已遗留在 `running` 的任务会置为 `failed`，错误码 `worker_interrupted`。用户重试会保留原失败记录、创建新 attempt。清理会保留活跃输入和元数据，已过期的临时候选返回 `410 media_expired`。原输入过期时，重新上传并使用新的提交键。[worker](../../services/worker/app/search_worker.py)

## 导入参考语料

把有使用权限的 GIF 放在 `data/reference`，提供 `manifest.json`。以下字段展示清单格式，实际导入时使用真实的 UUID、文件、授权和摘要。

```json
{
  "corpus_version": "team-corpus-v1",
  "assets": [{
    "reference_asset_id": "08b72e37-f396-49ae-8204-a9d791393af0",
    "title": "获授权原件的名称",
    "source_reference": "实际来源",
    "permission_note": "已记录的使用许可",
    "gif_path": "example.gif",
    "sha256": "<实际的 64 位小写 SHA-256>"
  }]
}
```

```powershell
docker compose exec api python -m services.common.reference_assets /data/reference/manifest.json
```

导入器在开启数据库会话前先校验每个 GIF 和摘要。随后每批读取、比对 400 行，最后一起提交。它检查来源和稳定 UUID，拒绝清单内重复 SHA 或不同目录 ID 指向同一 SHA。重复导入相同清单具有幂等性。同一资产 ID 的内容和来源必须稳定。新清单可以更新该资产当前 `corpus_version`，旧任务仍保存其原版本。发布新语料时停 worker，待文件、特征、清单和数据库目录一致后再启动。[参考素材导入](../../services/common/reference_assets.py)

`search` 返回 JSON 兼容数据，以下为最少使用到的字段，文件路径留在服务端。匹配项唯一、按分数降序，ID 可解析为声明版本的参考资产或当前工作空间内已就绪的收藏。空列表表示正常完成且 `no_candidates`。模型或语料不可用以及解码错误应由执行器明确报错。

```json
{
  "matches": [{
    "reference_asset_id": "08b72e37-f396-49ae-8204-a9d791393af0",
    "score": 0.87
  }],
  "model_version": "encoder-version",
  "corpus_version": "team-corpus-v1"
}
```

## 客户端 API

以下业务 ID 使用 UUID 字符串，JSON 字段为 snake_case。

| 端点 | 请求与返回 |
| --- | --- |
| `POST /search-requests` | multipart 提交 `image`、`client_submission_key`，可选 `user_keywords`、`client_item_id`。当前 API 还接受 `search_profile` 和 `description`。返回 `202` 和 `request_id`、`job_id`、`status`。 |
| `GET /search-requests/{request_id}` | 查询请求状态、关联任务和候选，含 `request_id`、`job_id`、`status`、`result_kind`、`candidates`、`error`。 |
| `GET /search-jobs/{job_id}/candidates` | 查看指定 attempt 的候选。 |
| `GET /candidates/{candidate_id}/media` | 获取校验后的候选媒体。传统 GIF 路径返回 `image/gif`，当前联网结果按实际 MIME 返回。已收藏候选可在临时文件过期后读取持久原件。 |
| `POST /search-jobs/{job_id}/reviews` | JSON 传 `decision`、`candidate_id`、`client_review_key`，返回 `201` 和 `review_id`。 |
| `POST /search-requests/{request_id}/retry` | JSON 传 `client_retry_key`，失败后重试，返回 `202` 和已接受的 attempt。 |
| `POST /search-requests/{request_id}/web-search` | JSON 传 `description`、`client_search_key`，创建独立的关联联网任务，返回 `202`。 |
| `POST /search-jobs/{job_id}/retry` | JSON 传 `client_retry_key`，重试指定失败的本地或联网任务，返回 `202`。 |
| `POST /candidates/{candidate_id}/save` | JSON 传 `client_save_key`，对已接受的联网 GIF 保存原件，返回 `202` 和资产、收藏及索引状态。 |
| `GET /saved-assets/{asset_id}` | 查询持久资产与索引状态。 |
| `GET /saved-assets/{asset_id}/media` | 从持久存储读取经校验的 `image/gif`，临时候选过期后仍可使用。 |
| `POST /saved-assets/{asset_id}/index-retry` | 将索引失败的资产重新排队。 |

提交时可以得到以下响应。

```json
{"request_id":"<uuid>","job_id":"<uuid>","status":"pending"}
```

轮询已完成的请求时会收到候选列表。

```json
{
  "request_id": "<uuid>",
  "job_id": "<uuid>",
  "status": "completed",
  "result_kind": "candidates",
  "candidates": [{
    "candidate_id": "<uuid>",
    "rank": 1,
    "score": 0.87,
    "media_url": "/candidates/<uuid>/media"
  }],
  "error": null
}
```

轮询还会返回 `job_kind`、`stage`、`local_job_id`、`web_searches`，让客户端刷新后恢复关联任务。候选按情况带 `source_url`、`image_url`、`provider`、`save_status`、`asset_id`、`index_status`。审阅端点记录用户接受结果；收藏端点持久化原件并返回长期使用的 `media_url`，worker 后续更新索引状态。读取收藏原件会校验摘要与动画帧数。未收藏候选的临时文件到期清理。

提交键与补搜键只对相同的输入和描述回放。复用相同键却改变内容返回 `409`。每个请求仅允许一个活跃的本地或联网任务。按具体联网任务重试可保留原结果和轨迹。收藏键回放同一候选与资产的映射，收藏资产按内容 SHA-256 去重。执行记录包含调用、下载、阶段轨迹、警告、耗时、停止原因及 agent 和模型版本。供应商凭据不写入执行记录。

状态依次为 `pending → running → completed / failed`。完成前 `result_kind` 为空，失败时返回 `error: {"code": "...", "message": "..."}`。业务 HTTP 错误通过 FastAPI 的 `detail: {"code": "...", "message": "..."}` 返回，入参不符合 schema 时返回标准 `422` 详情。键应为非纯空白字符串且最长 128 字符。复用上传键时，字节、关键词与本地项 ID 必须一致。回放返回原任务，应用按请求或具体任务 ID 查询最新状态。

审阅记录只追加。`accept` 需要已完成任务的候选，`reject_all` 的候选 ID 必须为空。相同审阅或重试键回放原记录，更改内容或请求、任务归属返回 `409`。用户是否播放或实际下载要另行观察。[路由实现](../../services/api/app/search.py) · [当前联网结果、预览与分页](../../services/api/app/meme_search.py)

传统联网 worker 读取 `WEB_SEARCH_TIMEOUT_SECONDS`（默认 60，最高 300）、`WEB_SEARCH_CALL_TIMEOUT_SECONDS`（默认 12，最高 60）、`WEB_SEARCH_MAX_DOWNLOADS`（默认及最高均为 6）。建收藏索引使用 `SAVED_INDEX_TIMEOUT_SECONDS`（默认 300，最高 600）。前两个联网超时传给共享 `SearchBudget`，旧 agent 最多两轮、最多三个结果。旧版 `SEARCH_AGENT_PROVIDER`、`SEARCH_AGENT_MODE` 和相应凭据由 Compose 传给 worker。网页使用的 `meme50-v2` 另有独立的调用与抓取预算；实际消耗在对应任务的执行记录中。日志及响应不应包含凭据。[当前供应商配置](../guides/online-search.zh-CN.md)

## 测试

使用 Python 3.11。下列命令检查开发依赖、静态规则和后端契约。开发 extra 包含 Starlette TestClient 需要的 `httpx2`。当前 CI 同时安装 `search` extra。

```powershell
python -m pip install -e ".[dev,search]"
ruff check .
pytest tests\unit tests\integration -q
```

SQLite 测试覆盖 HTTP、worker 与媒体行为。指定可创建数据库的本地测试连接后，PostgreSQL 套件会新建并删除随机命名的临时库。以下为本地测试环境示例，请使用自己的专用测试角色与端口。

```powershell
$env:TEST_POSTGRES_URL="postgresql+psycopg://postgres:postgres@localhost:5432/maie6000c"
pytest tests\integration\test_search_postgres.py -q
```

CI 在真实 PostgreSQL 上验证迁移的升级与降级、元数据一致性、八个并发的重复提交或审阅、重试、行锁领取、活动任务唯一性及跨任务审阅约束。八个相同审阅请求最终只生成一条不可变决定。

W07 曾在尚未接入真实检索的后端下显式期待 `retrieval_unavailable`，用下列设置运行部署冒烟测试。验证已接入真实推理的部署时，移除该环境变量，让执行错误直接导致测试失败。合成裁剪图用于接口验证，另用授权正例与无候选样本检验真实检索结果。starter 冒烟测试需要相应 Compose profile。

```powershell
$env:SMOKE_BASE_URL="http://localhost:8000"
$env:SMOKE_EXPECTED_SEARCH_ERROR="retrieval_unavailable"
pytest tests\smoke\test_smoke_search.py -q
```

### 历史部署记录

2026 年 10 月 27 日，在更新 FastAPI 和测试客户端依赖之前，团队以 Python 3.11.9、PostgreSQL 16 和 Docker Compose 完成一次验证。`ruff check .` 通过，编辑器未发现新增模块错误，44 个单元与集成测试及 2 个部署冒烟测试全部通过。重新构建容器、自动迁移后 API 就绪，搜索 worker 启动，选配的 starter case/AI 流程也通过。

保留数据卷重建数据库和 API 后，请求、任务状态、测试生成的两帧 GIF、接受审阅以及提交与审阅的幂等回放均保留。重启 worker 将遗留运行任务标记为 `worker_interrupted`，第二个实例被 advisory lock 拒绝。这轮持久性测试注入了排名并生成测试 GIF，冒烟测试显式期待 `retrieval_unavailable`。当时尚待验证的是真实语料检索、网页联调和设备端保存、播放。该轮出现依赖弃用警告，结束后清理了隔离容器和测试卷。

更新 FastAPI 与测试客户端依赖、补齐存储清理回归与语料导入后，历史运行 `pytest -q -W error` 为 45 通过、6 跳过、无警告。其中 4 项依赖 `TEST_POSTGRES_URL`，2 项依赖 `SMOKE_BASE_URL`。`ruff check .`、`uv pip check`、`git diff --check` 均通过。

随后用新镜像启动一次性 PostgreSQL 16、API 和搜索 worker，API 就绪且部署冒烟测试如预期得到 `retrieval_unavailable`。启用 `starter` 后 AI 与对应 worker 同样能工作，两项部署冒烟全部通过。临时 PostgreSQL 上的 4 个集成测试以 `-W error` 通过，覆盖迁移往返、并发幂等、行锁领取和 schema 约束。随后删除一次性服务与卷，保留宿主参考语料。搜索 API 的 Prometheus 指标标签使用 FastAPI 路由模板，避免把每个请求或任务 UUID 记录为新的标签值。

后续发布版本的真实网页找回、pgvector 迁移和重启下载记录可分别在[技术验收证据](README.zh-CN.md#验收证据与性能边界)查看。
