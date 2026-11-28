# 技术文档

[English](README.md) · [产品说明](../product/README.zh-CN.md) · [使用与部署](../guides/README.zh-CN.md)

MemeRetrieve 接收截图，返回可审阅、收藏和下载的 GIF 候选。排查一次检索时，用 `request_id` 找到原请求。每次本地检索、联网续搜和重试各有一个 `job_id`；收藏原件有独立的 `asset_id` 和索引状态。

## 运行组件与职责

| 组件 | 职责 | 实现 |
| --- | --- | --- |
| 网页与 FastAPI | API 在 `/web/` 提供网页，校验上传、持久化任务、管理会话并返回经过校验的媒体。网页轮询 API，展示搜索进度。 | [网页](../../web) · [API](../../services/api/app) |
| 搜索 worker | 从 PostgreSQL 领取持久化任务。本地任务调用固定版本 CLIP 编码器并按帧相似度检索，联网任务运行搜索 agent。导入和收藏另行排队建索引。 | [队列与索引生命周期](../../services/worker/app/search_worker.py) · [本地检索](../../services/retrieval/engine.py) |
| 搜索 agent 与公共媒体抓取服务 | 按配置由 HKUST 或 HKGAI 识图，DeepSeek 规划查询并检索网页。隔离的抓取服务获取公开网页及媒体，worker 对候选解码、去重、排序和发布。 | [搜索流程](../../services/search_agent/meme_pipeline.py) · [抓取服务](../../services/retrieval/public_fetch.py) |
| PostgreSQL、pgvector 与持久卷 | PostgreSQL 保存请求、审阅、账号、资产和索引版本，pgvector 保存帧向量以作精确搜索。媒体卷和模型卷保存原件及 NPZ 索引。 | [数据库与向量设计](../database-and-vector-search.md) · [Compose 配置](../../compose.pgvector.yaml) |

启用账号后，服务端按会话选择私人工作空间。新账号使用独立的 PostgreSQL schema 和媒体目录，参考素材与模型权重共享。设置 `BETA_INVITE_CODE` 后，新注册需提供邀请码。公测演练开启账号和私人库，把 API 绑定到回环地址，并在 API 和 worker 上设置 `ONLINE_SEARCH_ENABLED=false`。用户可以继续本地检索；联网续搜和外部 AI 标注关闭。[账号实现](../../services/api/app/accounts.py) · [演练配置](../../compose.public-beta.yaml)

## 从请求追到原件

| 步骤 | HTTP 契约 |
| --- | --- |
| 提交与续搜 | `POST /search-requests` 接收截图和客户端提交键，持久化后返回 `202`。`legacy` 发起本地检索，启用联网时 `meme50-v2` 直接发起联网检索。已有本地结果可用 `POST /search-requests/{request_id}/web-search` 创建关联任务。 |
| 查看进度 | `GET /search-requests/{request_id}` 返回请求和任务。用 `GET /search-jobs/{job_id}` 查看阶段、已验证数量及可用执行记录。**Search activity** 展示实际调用与计数。检索正常完成也可能返回零个候选。 |
| 分页与审阅 | `GET /search-jobs/{job_id}/results` 读取已发布结果。使用下一页游标时沿用结果版本、筛选条件和页大小。`POST /search-jobs/{job_id}/reviews` 记录用户决定。 |
| 收藏与下载 | `POST /candidates/{candidate_id}/save` 收藏用户选中的联网动画并排队建索引。`GET /saved-assets/{asset_id}` 返回索引状态，`GET /saved-assets/{asset_id}/media` 提供经过校验的 GIF 原件。索引失败可用 `POST /saved-assets/{asset_id}/index-retry` 重试。 |

客户端操作中断时，沿用原幂等键和相同的请求内容。HTTP `409` 可能表示重复键的内容不同，或当前已有活动任务。诊断失败时保留原始任务 ID。数据库限制每个请求同一时间只有一个活动任务。[检索与收藏路由](../../services/api/app/search.py) · [进度与分页路由](../../services/api/app/meme_search.py) · [后端开发手册](backend-guide.zh-CN.md)

## 排查检索

本地找不到目标时，先检查登录账号、收藏资产的 `index_status`、参考清单与模型修订。系统为每个 GIF 最多取八帧，每帧编码为 512 维向量，以该 GIF 的最高帧相似度排名。默认阈值为 `0.82`，最多返回三个达到阈值的不同资产。在 worker 日志中用 `vector_backend` 和 `reference_vector_backend` 区分私人收藏与公共参考库实际使用的 PostgreSQL 或 NPZ 路径。[采样、回退与迁移](../database-and-vector-search.md)

联网任务耗时较长时，按任务 ID 核对执行阶段、模型与搜索调用数、媒体下载尝试数、耗时、警告以及停止原因。worker 对每次任务的外部调用设有上限。供应商不可用、来源无法读取、候选不适用或用完预算可能造成失败或仅返回部分结果。专用本地演练中，联网请求会返回 `403 online_search_disabled`。[任务状态实现](../../services/api/app/meme_search.py) · [供应商配置](../guides/online-search.zh-CN.md) · [真实检索与未命中记录](../evidence/gif-acquisition/hkgai-web-offline-20261128.json)

## 开发与验证

在仓库根目录使用 Python 3.11。快速集成测试使用 SQLite。要运行 PostgreSQL 测试，把 `TEST_POSTGRES_URL` 指向有建库权限的专用测试连接；套件会创建并移除临时测试数据库。CI 会在普通 PostgreSQL 16 和带 pgvector 的 PostgreSQL 16 上分别运行。[后端 CI](../../.github/workflows/ci.yml)

```shell
python -m pip install -e ".[dev,search]"
python -m ruff check .
python -m pytest -q -m "not smoke and not live"
```

浏览器测试使用 Node.js 20，命令行中需要能运行 Python。以下命令覆盖网页 CI 用例。若修改涉及真实后端，还应按网页开发说明运行后端浏览器测试。[网页 CI](../../.github/workflows/web.yml) · [浏览器测试环境（英文）](../../web/README.md)

```shell
cd web
npm ci
npx playwright install chromium
npm run format:check
npm test -- client.spec.js design.spec.js meme50.spec.js mobile-compat.spec.js
```

容器 CI 构建 API、worker 和抓取镜像并执行冒烟测试。`main` 上的发布任务会在同一提交的必要检查通过后，将已测镜像发到 GHCR。排查运行中的部署时，先用 `/health/live` 检查进程，再用 `/health/ready` 检查数据库与存储，最后跟踪实际任务直至完成，验证 worker 和模型。[镜像发布流水线](../../.github/workflows/container-release.yml) · [部署指南](../guides/README.zh-CN.md)

## 验收证据与性能边界

| 证据 | 结果与适用范围 |
| --- | --- |
| [授权参考库](../../submissions/week13/local-corpus-evaluation.json) | 12 个参考 GIF 各取一帧作为查询，首帧索引 Top-3 命中 11 个，多帧索引命中 12 个。独立用户截图和更大图库仍待评测。 |
| [联网网页验收](../../submissions/week13/browser-release-verification.json) | 用户提供来源线索后找回 44 帧地球 GIF。收藏并离线重启后，以另一帧找回同一原件，两次下载与独立参照逐字节一致。 |
| [旧库迁移](../../submissions/week13/pgvector-verification.json) | 恢复后旧账号保留原资产 ID 和 SHA。帧向量完整时通过 pgvector 命中，主动制造镜像缺失后通过 NPZ 回退命中。共享参考库同步了 96 帧。 |
| [邀请码本机演练](../../submissions/week13/public-beta-rehearsal.json) | Chrome 在重建 API 和 worker 前后分别上传第 13 帧、第 29 帧截图，两次都首位命中同一收藏。两次下载的 1,001,718 字节完全相同。该记录验证了回环地址上的部署。 |

精确匹配的计算量随候选帧数增长。模型启动、排队和原件校验也会影响端到端耗时。每账号规模下的延迟、公网可用性和真实用户命中率需要分别测量。[容量基准方案](../database-and-vector-search.md#容量与演进条件)
