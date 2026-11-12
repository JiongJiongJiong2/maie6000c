# 当前执行范围：HKUST + DeepSeek Flash

2026-11-12，香港时间。此文记录用户最新要求，优先于此前 Google Vision / Brave 方案和旧 A0/A2 服务约束。全程单 agent，不调用 subagent。图片必填、文字可选、PNG/JPEG/WebP/GIF、约 50 个不重复动静态表情的产品目标不变。

## 角色与实际接口

| 角色 | 当前实现 | 输入与输出 |
| --- | --- | --- |
| 看图、OCR、结合网页证据复核身份 | HKUST 网关，默认 `gemini-2.5-flash-lite` | 上传文件规范化后的最多四帧 → 可见事实、图中文字、动作/情绪、不确定实体；证据复核最多再调用一次 |
| 查询规划 | DeepSeek 默认 **`deepseek-flash`**，关闭 thinking | 只接收已提取的视觉事实、OCR、偏好及检索证据 → 2–5 条不超过 128 字符的真实搜索查询，至少两种角度 |
| 联网搜索、获取核验出处 | DeepSeek 官方 `POST /v1/tools/search` | 共享同一 DeepSeek key；每次最多 50 个真实网页结果，核验使用最多 5 个实际出处 |
| 从网页找到媒体、下载 | 现有隔离 public fetcher、通用 HTML/结构化媒体提取 | 抓取真实搜索返回的公开页面或直接媒体 URL，解码与校验真实 PNG/GIF 等字节 |
| 重排与去重 | 本机固定版本 CLIP、SHA、内容分组 | 不调用额外平台 API；保留现有相关性阈值与内容去重 |

只允许上述两个账号服务作为当前任务的模型/检索供应商。正式 factory 不会选择 Google 直连 Gemini、Google Cloud Vision、Brave、Tavily 或其他备用供应商。仓库的旧适配器保留兼容性，但本 profile 不调用。既有 Google Cloud 项目及凭据没有被删除，也不再作为任务依赖；无需开通 Google 结算或注册 Brave。

DeepSeek 的聊天模型不会凭空联网。本实现实际调用其官方 Search 端点，再访问真实结果页面。它提供网页搜索，并非原始图片像素反搜。因此 `reverse_image_provider=disabled` 会明确记入 trace，不能把网页搜索标成“真实以图反搜”。页面或媒体 URL 必须来自实际检索/抓取响应，不能由模型编造。

## 当前配置

真实 key 只在本项目 `.env`，不提交、不复制进报告或聊天。学校 key 已存在，用户提供的 DeepSeek key 已通过隐藏输入保存。

```dotenv
MEME50_PROVIDER_POLICY=hkust-deepseek-v1
MEME50_VISION_PROVIDER=hkust
MEME50_HKUST_MODEL=gemini-2.5-flash-lite
MEME50_HKUST_API_KEY=<local-only>
MEME50_DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_API_KEY=<local-only>
MEME50_KEYWORD_PROVIDER=deepseek
MEME50_REVERSE_IMAGE_PROVIDER=disabled
```

安全检查：`.venv/bin/python -m scripts.configure_meme50 --check`。只要求学校和 DeepSeek 两把 key；仅检查存在性，不宣称已获授权。

重新配置学校：`.venv/bin/python -m scripts.configure_meme50 --vision-only`。
重新配置 DeepSeek：`.venv/bin/python -m scripts.configure_meme50 --deepseek-only`（`--search-only` 是同义选项）。模型提示直接回车采用显示的默认值。

API key 仅进入对应官方域名的认证头；不会进入 DB 配置、runner JSON、前端或媒体 fetcher。测试默认隔离本机 `.env` 及真实 key，仅用受控测试值。DeepSeek 使用会消耗用户已有账号额度；没有新开付费账户、绑定结算或购买套餐。

## 管线与预算

上传原字节与 SHA → 多格式解码、代表帧 → HKUST 理解 → 必要时 DeepSeek 网页核验 + HKUST 对照图片复核 → DeepSeek Flash 规划查询 → DeepSeek 网页检索 → 真实页面/媒体提取 → 多帧图像与文本排序 → SHA/内容分组 → 验证草稿 → DB 最终事务、revision、筛选与分页。

单次任务最多 **3 次模型调用**（初次看图、可选看图复核、Flash 查询规划），不是无限重试。搜索调用、查询数、下载数、页面数、字节、磁盘与截止时间沿用共享 ledger：最多 16 次搜索调用、6 条查询、120 次原媒体尝试、40 页、512 MiB；初始 180 秒，总上限 300 秒。模型调用上限及 worker 最终协议检查已同步为 3，其余门槛没有放松。

查询规划失败时可继续使用学校识图已生成的查询，但须记录失败，不能在 provider 自检或完整验收中假装 DeepSeek Flash 成功。没有 DeepSeek 搜索权限或额度时明确失败，不切换其他服务。

## 验收范围修订

| 门槛 | 当前要求 |
| --- | --- |
| A0 | HKUST 看图、DeepSeek Flash 规划、DeepSeek 网页召回及核验四种调用真实成功；正式 job 配置与 probe 指纹匹配。仅 key 非空不算通过 |
| A1 | 原自动图片理解、空文字、至少两角度查询、真实联网核验案例要求保持；不能用文件名、预写 caption 或目标 URL 替代 |
| A2 | 同一正式任务有 DeepSeek Flash 查询规划 trace、真实 DeepSeek 网页结果和实际验证媒体；不再要求 Google 像素反搜通道，不能伪装反搜已通过 |
| A3–A8 | 原真实 API/worker/DB、三例各单次 40–50、至少 12 例家族隔离留出集、浏览器、回归/部署、真人审阅、真实成员独立复现保持 |

相关性门槛保持 Top10 明确相关宏平均至少 90%、实际返回列表明确相关宏平均至少 80%；全部案例计入分母，内容重复为零。网页数量、预览数量、HTTP 200 或受控测试成功均不能替代最终媒体数量和真人质量验收。

本轮已真实通过 provider 自检：`.cache/meme50/acceptance/hkust-deepseek-probe-20261112-01/probe.json`。学校识图约 4.125 秒；DeepSeek Flash 规划约 3.8 秒，生成五条查询；DeepSeek 召回 50 条网页线索，核验五条出处。50 条网页线索不是 50 个通过验证的表情。该记录只证明服务联通，后续代码/配置修改后仍需新版本自检，不把旧记录拼接冒充新版本。

## 原执行 agent 接续步骤

1. 阅读本文件及当前改动，保留原 `codex/real-gif-acquisition` 工作区、未提交实现、历史 DB 和失败证据。用户已明确取消 Google Vision/Brave 必需条件，不再询问这些 key、结算或账号。
2. 按最新角色修订恢复原完整验收目标。若 goal 工具不能直接改写目标文本，以本文件作为用户范围修订继续；不要为了换文字把未完成目标标 complete，也不要另造成功记录。
3. 先检查现有本机 API/worker/fetch/DB 的实际状态。代码已改，旧进程需要刷新；避免启动两个队列消费者。保留旧数据，不通过删除库或卷解决启动问题。
4. 重新跑当前版本真实 probe，使用全新目录；然后空文字小规模实际 job，确认 DB/runner/网页都使用 `hkust-deepseek-v1` 和 `deepseek-flash`。确认调用总数可到 3，学校和 DeepSeek key 都不进入 job 配置或浏览器。
5. 调通真实网页到媒体的来源提取和下载。保留逐层 metadata、页面、解码、低分、重复、最终组数。发现模板、广告、静态小图或来源结构问题，按真实失败修复通用提取或排序，不编造 URL、不用静态 fixture 代替。
6. 再做三个资源充足开发案例各单次 40–50；用开发集调参。冻结后运行新留出版本，既有留出若被用于调参则换版本。正式网页、真人标注与真实成员复现按原标准完成。
7. 只在 A0–A8 实际满足后报告完整通过。普通排障自行推进，不反复问“要不要继续”；确实需要真人判断时先准备具体材料。

官方接口依据：[DeepSeek Search](https://api-docs.deepseek.com/api/search/)、[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[HKUST 网关接入](https://itso.hkust.edu.hk/services/general-it-services/generative-ai-tools/hkust-genai-api-service/integration-ai-tools)。
