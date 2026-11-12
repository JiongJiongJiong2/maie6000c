# 图片主导检索 meme50-v2

最新已确认重复失败的修复、回归和交付见 [2026-11-13 去重修复](meme50-dedup-fix-20261113.md)。当前去重为 `meme50-temporal-local-v8`；原 v8 评测产物和真人 pending 状态作为历史记录保留。

最新数量、网页、回归及 pending 项见 [v8 结果](meme50-v8-results.md)，修复历史见 [实测记录](meme50-live-20261112.md)，真人操作见 [审阅与复现](meme50-human-review.md)。历史完整验收工具、真实源站修复、新留出及状态见 [2026-11-12 执行报告](meme50-acceptance-20261112.md)。`meme50_acceptance` 提供 probe/run-suite/review/score/finalize；不会将未知标签、零候选或未复现自动判为产品通过。

实现和修复交付分支是 `codex/real-gif-acquisition`，见 [PR #9](https://github.com/JiongJiongJiong2/maie6000c/pull/9)。历史 v8 运行基线为 `c34d9f6` 加对应源文件快照。正式入口仍为 `/web/`，默认图片必填、描述可选、最多 50 条；旧 API 默认 `legacy` 三候选不变。

**当前供应商策略为 `hkust-deepseek-v1`：只使用学校 HKUST API 和 DeepSeek，DeepSeek 默认 `deepseek-flash`。** 两项凭据已配置，真实识图、Flash 查询规划、网页召回和核验自检已通过；三个预筛案例各单次返回50个机检媒体，真人相关性、视觉重复与成员复现仍待完成。Google Vision/Brave 不再必需，当前执行与验收范围以 [最新执行说明](hkust-deepseek-execution.md) 为准。旧失败记录保留于 [历史验收记录](meme50-verification.md)，不改写为成功。

## 数据流和服务边界

上传原字节及 SHA → 直接创建 web job → 本地解码、规范化和代表帧 → HKUST 看图/OCR → 不确定身份的显式 DeepSeek 网页核验及至多一次 HKUST 对照图片修正 → DeepSeek Flash 规划查询 → DeepSeek 官方网页检索 → 来源 rank 融合、公开页面提取、原媒体获取 → 固定 CLIP 图像/文本多帧评分 → SHA 与内容分组 → 验证草稿 → 单次最终事务、稳定 revision、筛选分页。当前无像素反搜服务，网页检索不伪装为以图反搜。

图片**会外发**：最多四张、最大边 768 的派生 PNG 帧发送给 HKUST 网关；视觉事实、OCR、偏好及核验线索发送给 DeepSeek。原文件名、本机路径和独立目标 URL 不作为识别输入。图中文字及检索片段只作不可信数据，不能授予工具权限。证据关系绑定实际返回的出处 ID/URL，支持、冲突和未解决状态分别保留。

API 不加载 CLIP 权重。独立 worker 调用 JSONL 子进程；父进程限制行长 256 KiB、总输出 4 MiB、截止时间和事件顺序，验证每个原文件及预览后写草稿。EOF、重复 final、越界路径、SHA/格式不一致不能发布成功。硬超时杀死进程组。最终结果最多 50 个内容组，草稿不属于稳定排序。

媒体出口 `media-fetch` 不接收模型/数据库凭据、不挂载媒体卷、不加入数据库所在默认网络。公网 URL 每跳校验；解析结果全部为公网，实际 TCP 连接固定到校验后的数字 IP，再复核 socket peer。httpcore 保留原 host、TLS 证书验证和 SNI；没有关闭证书验证。不是单纯 DNS 预检查。Docker 默认非 root、只读文件系统、去除 capabilities。公开 CDN 无需增加源码白名单。系统 DNS 遇 fake IP 会明确失败；可选 `MEME50_DNS_MODE=doh` 使用 Cloudflare `1.1.1.1` 的验证 HTTPS DNS 服务，该服务只收到域名，不收到图片。

直接媒体优先；通用页面支持 og/twitter、JSON-LD、srcset、合理 lazy 属性和相对链接，每页最多四项，排除明显图标。Tenor v2 使用真实公开 WebP 主素材及带自身永久链接的相关卡片，每页最多十四项，共享原有全局预算；旧 GIF 路径和 Commons/parrot 专用解析保留。当前没有浏览器渲染兜底；需 JS、登录或拒绝访问的来源会保留失败并尝试其他结果，不承诺任意站点可抓取。

## 格式、评分和限制

真实解码识别 PNG/JPEG/WebP/GIF；单帧（包括 GIF）为 static，多帧为 animated。动画 PNG/WebP 已有解码及代表帧测试；原文件无损导出，浏览器动画兼容性仍需实际外部结果验收。GIF 支持时间采样与 Pillow disposal 组合。媒体 API 的 MIME、后缀及 SHA 来自解码信息；不会把静态图转成 GIF。静态候选只提供预览、来源及下载。旧 GIF 收藏保留，未完成的收藏索引仍明确失败。

CLIP 模型 revision 固定为 `37000f5cdccec47a3f6f83142bff131370757470`，文本 tokenizer 与图像模型同源。开发评分 `meme50-rank-dev-v1-unvalidated`：视觉 .60、文本语义 .25、多帧覆盖 .10、质量 .025、标题/偏好词 .025；初始阈值 .55。它尚未通过真实开发集校准，不能推断相关性或标为正确率。CLIP 动作/OCR 区分能力有限，真人审阅必须独立进行。

默认总时限 180 秒，最多 300；单调用 18 秒，最多 40。全任务共享最多 2 次视觉调用、16 次搜索、6 条查询（核验查询也计入）、500 条保留元数据、250 次预览、120 次原文件、40 次页面、120 次跳转、512 MiB 网络与 512 MiB 保守磁盘配额、并发 6。补搜不重置。磁盘按 runner、草稿、最终副本的三倍原文件加预览预留。单媒体 12 MiB、20 MP、1000 帧、100M 总解码像素。provider 不提供 offset 的图片接口不伪造分页。

时间轴指纹保留重复帧的位置，合并同动画尺寸/压缩/帧率版本；不同动作或有意义文字变化须保留。明确帖子身份可帮助分组，通用页面 URL 不作内容身份。最终一组一项，优先清晰版本；不足时明确展示真实数量和原因。

## 配置和启动

Python 3.11、Docker Desktop、可读模型缓存。不要覆盖已有 `.env` 或删除数据卷。只需一把学校 primary/secondary key 和用户自己的 DeepSeek key；使用以下私密配置（不提交）：

```dotenv
MEME50_PROVIDER_POLICY=hkust-deepseek-v1
MEME50_VISION_PROVIDER=hkust
MEME50_HKUST_API_KEY=...
MEME50_HKUST_MODEL=gemini-2.5-flash-lite
DEEPSEEK_API_KEY=...
MEME50_DEEPSEEK_MODEL=deepseek-flash
MEME50_VERIFY_ENTITIES=true
MEME50_DNS_MODE=system
```

当前默认模型已实际调用验证；key 存在仍不等于整个任务通过，见 [当前授权状态](meme50-authorization.md)。仅必要 worker 收到密钥，浏览器及 fetch 服务不收到。其余 `MEME50_*` 限制见 `.env.example`；不得为单例临时降低评分门槛补数量。

已有本地库和索引的工作区：

```bash
.venv/bin/python -m pip install -e '.[dev,search,retrieval]'
.venv/bin/python scripts/download_model.py
.venv/bin/python -m scripts.run_local_demo
# 正式网页 http://127.0.0.1:8000/web/
```

启动器保留专用数据库密码文件 `.cache/local-demo.env`，启动已有 PostgreSQL 及只绑定 `127.0.0.1:8120` 的隔离 fetch 容器，执行迁移，再启动 API 和独立 worker。已有历史库先备份；不以删除库获得干净演示。首次本地库准备按 [旧启动说明](local-demo.md) 执行。完整 Compose：`docker compose up -d --build db media-fetch api worker`，先按原说明准备共享模型卷；worker 的 retrieval 依赖在 `worker` target，API 不装 torch。运行 `alembic upgrade head` 到 `20261111_0004`；有新 profile 或静态/高 rank 数据时降级明确拒绝且不删数据。

前台启动器 Ctrl-C 停 API/worker，数据库与 fetch 保留；如需停止容器，使用原项目名和 `.cache/local-compose.yaml` 执行 `docker compose ... stop`，不要使用 `down -v`。日志 `.cache/local-api.log`、`.cache/local-worker.log`；关联 request/job ID 排错。正常检索不足、部分服务故障和全部失败分别报告。重试生成新 attempt，历史失败不改成成功。草稿保留一天，最终候选沿用媒体保留天数；清理跳过活跃 job，原输入和收藏沿用原规则。

## HTTP 与真实验证

`POST /search-requests` multipart：`image`、`client_submission_key`、`search_profile=meme50-v2`、可省略的 `description`、可选 `target_count`（1..50）。相同 key 及内容可重放，偏好/图片/profile/count 不一致返回 409。旧 `user_keywords` 可兼容，和 description 不一致返回 422。

- `GET /search-jobs/{id}`：profile/version、阶段、分析、计数、revision、partial、错误。
- `GET /search-jobs/{id}/previews`：已验证 provisional 预览。
- `GET /search-jobs/{id}/results?limit=20&media_kind=all&revision=...`：仅已完成稳定结果；cursor 绑定 job、revision、筛选及页大小。变化返回冲突，不能混页。
- `GET /candidates/{id}/preview`、`/media`：实际原格式及校验；过期与损坏明确返回错误。
- `POST /search-jobs/{id}/retry`：既有幂等 retry key 契约，新 attempt 保持 v2。

```bash
.venv/bin/python -m scripts.verify_meme50 \
  --base-url http://127.0.0.1:8000 \
  --image .cache/meme50/inputs/dev-01.gif \
  --target-count 50 --out .cache/meme50/runs/new-attempt
```

省略 description 是真实空文字。脚本只调用运行中 API，验证幂等上传、最终分页/筛选/revision、每条解码/MIME/SHA，保存结果文件及 `evidence.json`。exit 0 只说明机器契约通过；40..50 数量和真人相关性另列，不能将无结果或低质量视为通过。失败 exit 2，协议或网络异常 exit 3。`DEVICE_TOKEN` 只从环境读取，不写证据。

普通 CI 使用显式受控响应，不调用付费服务。真实 provider 与质量验收用上述脚本及冻结清单运行，禁止将目标题注入查询或合并多次结果。输入版权归原权利人；来源缓存/保存是否符合部署用途需按相应服务约定核对，不能由抓取成功推断授权。
