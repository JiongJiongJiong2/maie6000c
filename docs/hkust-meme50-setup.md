> 历史配置记录：下文 Google Vision / Brave 章节已经被当前 HKUST + DeepSeek 范围替代，不再要求这些账号或结算。当前配置与实测请看 [执行范围](hkust-deepseek-execution.md) 和 [最新实测](meme50-live-20261112.md)。

# HKUST 学校 key 接入 meme50

> 历史接入记录：用户已将当前任务改为只用 HKUST + DeepSeek，默认 DeepSeek Flash。请以 [最新执行说明](hkust-deepseek-execution.md) 为准，不再办理本文旧方案中的 Google Vision 结算或 Brave 授权。

2026-11-12，香港时间。HKUST 识图已完成真实调用，完整检索验收仍未通过。

## 已完成

- `MEME50_VISION_PROVIDER=hkust` 选择学校网关；`gemini` 保留原 Google 直连方式。
- HKUST 固定使用 `https://hkust.azure-api.net/hkust-genai/v1/chat/completions`，认证头为 `api-key`。不会把学校 key 发送给 Google 直连接口或 Brave。
- 默认学校模型为 `gemini-2.5-flash-lite`。模型列表已实际确认该账号可访问；真实 GIF 抽取四帧，以空文字输入完成图像分析并生成四条不同角度查询。不是使用预写 caption 或文件名提示。
- 首次实际响应使用了契约外的 `hypothesized` 状态而被拒绝。已补充严格状态枚举要求；无外部证据的身份仍保留 `uncertain`，不会自行升级成已核验。
- 初始分析与联网证据修正复用同一 provider、解析契约及调用/字节/时间预算。学校模型本身不等同于反搜或网页搜索服务。
- worker 记录的配置与 runner JSON 不含学校 key；Compose 只把它注入 worker，前端与媒体下载服务没有该字段。

## 只填写一把学校 key

```bash
cd "/Users/somers/Documents/ChatGPT/600c-course project/maie6000c"
.venv/bin/python -m scripts.configure_meme50 --provider hkust --vision-only
```

`MEME50_HKUST_API_KEY` 输入 HKUST 门户的 primary 或 secondary 中任意一把；`MEME50_HKUST_MODEL [gemini-2.5-flash-lite]` 直接回车。输入隐藏，保存到本项目 `.env`，权限 0600。模型访问是否成功由真实 probe 判断。

等 Google Vision 和 Brave 的授权开通后，只补检索凭据：

```bash
.venv/bin/python -m scripts.configure_meme50 --search-only
```

这个命令只问 `MEME50_GOOGLE_VISION_API_KEY` 和 `MEME50_BRAVE_API_KEY`，保留学校 key 与模型，不会再问主/备用学校 key。

仅检查配置存在性：

```bash
.venv/bin/python -m scripts.configure_meme50 --check
```

`authorization_verified=false` 表示此命令没有发出服务请求。完整检查退出 2 表示仍缺检索授权；不能把只完成识图解释为完整验收通过。`--check --vision-only` 只检查识图配置。

## 真实验证与后续

```bash
.venv/bin/python -m scripts.meme50_acceptance probe \
  --image .cache/meme50/inputs/dev-01.gif \
  --out .cache/meme50/acceptance/<新的且不存在的目录>
```

最终代码的成功记录：`.cache/meme50/acceptance/hkust-probe-20261112-03/probe.json`。visual 为 passed，用时约 3.94 秒，生成四条查询。学校模型、实际输入 SHA、四帧位置、查询和耗时均有记录；该次整体仍为 pending。第一次成功另存 `hkust-probe-20261112-02`，旧失败保留在 `hkust-probe-20261112-01` 及单独诊断文件中。

Google Cloud 专用项目名称为 `maie6000c-meme50`，项目 ID 为 `fast-audio-514504-c0`，与原 GIS 项目隔离。Cloud Vision API 已启用，`maie6000c-meme50-vision-local` 已在创建前选定仅允许 Cloud Vision API，保存至本项目 `.env`。真实反搜调用仍返回 403 / `BILLING_DISABLED`，记录 `.cache/meme50/vision-key-probe-20261112-01.json`。密钥存在不代表服务已能调用；未绑定结算或付费。Brave 账号尚未登录、key 尚未配置。

当前需要账号所有者完成：为该专用 Google Cloud 项目自行处理结算前提；在 Brave API 门户完成登录及必要的服务授权/条款/计费确认。新的 API key 创建按浏览器规则单独确认。不要把学校的备用 key 放进 Brave 字段。

授权完整后，按现有 A0–A8 文档继续真实 API/worker、三例单次 40–50 条、留出集、正式网页、真人审阅及成员复现；不用重写已有检索和验收系统。

## 凭据与测试隔离

配置层修复了 dotenv 别名优先于显式构造参数的问题。普通非 smoke 测试屏蔽本机 `.env` 及真实凭据环境变量；配置工具测试只在临时目录中明确启用受控 `.env`，回归测试验证四类 key 的显式参数优先级。不把真实 key 用作测试数据。

隔离修复前测试曾读取本机真实环境并带入失败输出，已告知账号所有者。修复后的测试只使用受控凭据；文档、代码、截图和验收汇总不包含真实值。

最终非 smoke 回归：**310 passed、5 skipped、2 deselected**。五项 PostgreSQL 专用测试因当前数据库未启动而未完成；不以旧版本的 PostgreSQL 结果替代。脱敏日志：`.cache/meme50/hkust-setup-tests-final-20261112.txt`。早期字体缺失、测试环境继承 demo 开关、数据库连接拒绝的失败保留并分别处理；最终使用本机已有字体、关闭 demo 的隔离测试环境。Ruff 和 `git diff --check` 通过。没有改动数据库迁移或检索评分阈值。

## 官方依据

- [HKUST API 服务、认证与订阅](https://itso.hkust.edu.hk/services/it-infrastructure/hkust-genai-api-service)
- [学校支持模型及实时 models 端点](https://itso.hkust.edu.hk/services/general-it-services/generative-ai-tools/hkust-genai-api-service/supported-models)
- [HKUST 接入说明](https://itso.hkust.edu.hk/services/general-it-services/generative-ai-tools/hkust-genai-api-service/integration-ai-tools)
- [Cloud Vision 开通前提](https://docs.cloud.google.com/vision/docs/setup)
- [Brave API 开通说明](https://api-dashboard.search.brave.com/documentation/quickstart)
