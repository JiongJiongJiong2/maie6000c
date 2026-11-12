# meme50 完整验收执行记录 · 2026-11-12（香港时间）

持续目标后续已加固验收证据格式，见 [门槛审计](meme50-goal-audit.md)。下文保留原版本运行记录；新 finalize 需使用带锁定 labels.csv 的新 score 输出，不能把历史状态直接当成当前版本通过。

**最终状态：pending，未完整验收通过。** 汇总器实际退出 2；A7 工程回归与适用部署检查通过，A0–A6、A8 尚未满足。当前仍没有 Gemini、Google Vision、Brave 授权，正式自动搜索均失败为 `visual_provider_unconfigured`。没有使用 fixture、旧缓存、手写 caption、目标 URL 或文件名语义替代模型；没有填写真人标签或成员签名。

本轮保留 `codex/real-gif-acquisition` / `c34d9f6` 以及此前所有未提交改动、数据库和失败记录。没有推送、合并、删除卷或创建付费账号。全程单 agent。代码及无凭据配置快照在 `.cache/meme50/acceptance/20261112-v2/baseline/`，最终每个 probe/suite 都另有对应快照。

## 本轮新增与修复

| 文件 | 实际改动 |
| --- | --- |
| `scripts/meme50_acceptance.py` | 可执行的 probe、run-suite、review、score、finalize；来源/配置快照；全案例分母及独立 gate |
| `scripts/meme50_review_ui.js` | 本地真人审阅表单，所有判断默认 unreviewed，身份默认空白；导出绑定身份的 CSV，不发送数据 |
| `scripts/verify_meme50.py` | 拒绝覆盖旧目录，保存真实分页与 replay 状态；可与实际数据库逐条对账；修复慢 GIF 重放时状态推进的误判 |
| `scripts/verify_meme50_browser.mjs` | 按实际 candidate ID 校验分页集合、筛选与刷新位置；下载交给真实解码/DB 复验；动画截图像素变化、暂停、移动布局及按需加载断言；明确缺失覆盖，不因零卡片跳过而宣布通过 |
| `scripts/verify_meme50_media.py` | 浏览器下载的格式、MIME、帧数、SHA、后缀及可选数据库 membership/revision 复验 |
| `services/search_agent/meme_providers.py` | 脱敏区分 HTTP 授权/额度/模型端点错误与 HTTP 200 内业务错误；只存枚举与数字，不存供应商 message、header、key 或 base64 |
| `services/search_agent/meme_pipeline.py`、`meme_types.py` | 召回通道与原文件尝试计数、融合通道身份；实际媒体 HTML 包装页的有界获取修复；共享 ledger 不重置 |
| `web/meme50.js` | 卡片标记真实 candidate ID、rank、类型、SHA，供实际页面集合检查 |
| `docs/meme50-evaluation-v2.json` | 新冻结版本，保留旧 emoji 清单；5 个开发/工程输入、12 个实际梗图留出输入 |
| 新/扩展测试 | 错误业务响应、评分分母、未知标签、跨 attempt 标签、重复组、旧目录保护、家族泄漏、容器指纹、状态重放竞态、包装页预算及真人表单 |

没有重搭 API、worker 或迁移，没有改动评分阈值或放松内容去重凑数。排名仍为未校准的 `meme50-rank-dev-v1-unvalidated` / 0.55；没有真实数据支持进一步校准或质量结论。

真实来源排障发现：部分 `media1.tenor.com/m/...gif` 返回 HTTP 200 HTML，而不是 GIF。包装页中实际有 `c.tenor.com/...gif` 的 img 链接。实现读取实际页面线索再获取，限制一次包装层及已有每页四线索，原文件/页面/字节/时限共用 ledger；没有猜测替换 host、放行 fake IP 或关闭 TLS。源站原始失败和重试均留档。此结果证明获取边界修复，不证明自动识图或相关性。

## 实际检查结果

- Python／PostgreSQL：**292 passed，2 deselected**。专用测试数据库实际创建/迁移/销毁；没有清空项目历史库。日志 `python-postgres-delivery.txt`。
- 浏览器：**18 passed**。client/design/meme50 受控响应回归及真人表单默认状态/导出约束；不是公网成功证据。日志 `web-tests.txt`。
- 旧三候选真实 smoke：**1 passed**，日志 `legacy-smoke-direct.txt`。另一个 `/cases` 分诊 smoke 属于未启动的 starter triage profile，未运行。主套件的两项 deselected 与单独执行结果分开记录。
- Ruff、diff check、Prettier：通过，最终退出码及输出分别留档。
- 最终非 root、只读 worker 镜像：UID 10001；只读模型卷实际运行图像与文本 CLIP，均 `[1,512]`；实际连通隔离 media-fetch 健康端点。容器和宿主机运行代码指纹、配置指纹完全一致。不是完整容器 API/DB/worker 产品栈成功宣告，正式业务仍是宿主机 API/worker + Docker PostgreSQL/fetch。

最终运行代码指纹：`fa3c001d875d16d3195934222568e394247657b31d6356df341760f47a6703f0`。
无凭据配置指纹：`b74768e995d91fb39e8f60b39ef8326c45cc434ab61c1f65750aa5a3d436f2f6`。

代码指纹对共同的运行文件计算，因此能在宿主机与镜像比较；另保存含测试与 Docker 配置的完整 source snapshot 指纹和归档。图片、模型权重、环境密钥不在快照中。

中间失败未删除：首次全回归继承了 `ENABLE_DEMO_LIBRARY=true`，默认关闭断言失败；改用隔离测试配置后原断言通过。旧 smoke 未设本机 NO_PROXY 时读取超时，显式本机直连后通过，未改全局代理。浏览器验收器首次缺少 API baseURL，修复并重跑；大 GIF 的幂等状态推进问题也保留原 attempt。容器临时检查脚本第一次从 `/tmp` 执行时缺少 `/app` 模块路径，修正检查脚本后实际镜像检查通过。没有把这些失败文件改写成成功。

## Provider 与真实任务

最终 probe 在宿主机、以及交付 worker 镜像内都实际执行：

| 调用 | 状态 | 原因/计数 |
| --- | --- | --- |
| Gemini generateContent | pending | `visual_provider_unconfigured`，模型调用 0 |
| Google Vision Web Detection/OCR | pending | `image_search_unconfigured`，搜索调用 0 |
| Brave Images | pending | `keyword_search_unconfigured`，搜索调用 0 |
| Brave Web 核验 | pending | `entity_verifier_unconfigured`，搜索调用 0 |

配置仍写 `gemini-3.8-flash`，**没有确认当前账号能访问该模型**；有授权后必须从实际账号模型能力完成验证，不把默认字符串视为通过。官方能力参考：[模型](https://ai.google.dev/gemini-api/docs/models)、[Web Detection](https://docs.cloud.google.com/vision/docs/detecting-web)、[Brave Images](https://api-dashboard.search.brave.com/api-reference/images/image_search)。参考接口文档不代表已授权调用成功。

小规模 target=5 检查已执行，仍因授权失败。随后逐例保存目标 50 的正式 API 记录：最终开发 5/5、留出 12/12 都在云端视觉配置处失败，每例结果 0、没有 revision、没有真实检索查询、没有候选下载。幂等重放、输入 SHA、实际 job 与阶段均保留；未把不同 attempt 合并。

完整逐例信息在：

- `.cache/meme50/acceptance/20261112-v2/development-delivery/suite.json`
- `.cache/meme50/acceptance/20261112-v2/heldout-delivery/suite.json`
- 每例子目录 `evidence.json`：request/job ID、输入 SHA、实际配置、ledger、stage、错误及计时。
- `scores-development/scores.json`、`scores-heldout/scores.json`：所有案例保留在分母内。

留出有效性统计为 0/12 成功、12/12 技术失败，数量分布全部 0。按规定包含技术失败的 P10、返回列表相关比例及固定分母 P50 均为 0；**这不是已经测得“语义相关性为 0%”**，而是授权失败导致整个流程没有产物。人工质量状态仍 pending，不能把空标签表当作已审阅。

只有失败任务的终止时间可测，首批预览、成功子集 p50/p95 均没有观测值。具体 p50/p95 保留在 score 文件；不能将快速配置失败的耗时宣传为检索性能。外部付费调用计数均为 0，没有供应商账单，不估造价格。

## 新留出与人工材料

[新冻结清单](meme50-evaluation-v2.json) 覆盖真实中文文字、真人反应、卡通/动物、截图裁剪，PNG/JPEG/WebP/GIF 全覆盖，12 例中 8 例空文字、4 例动画。原始及派生文件使用随机本地名，逐条记录源 URL、原始/输入 SHA、转换与裁剪，文件均在忽略目录。

在传输排障中看过的熊猫与 Office 输入已转为 engineering development，不冒充未见留出；另加入两个新家族补足 12 例。旧 8 Twemoji/4 Noto 清单不覆盖、不替代新分布。新清单仍存在 Tenor 来源偏倚，不能外推到所有平台。失败发生在模型调用前，没有拿留出查询/评分结果调参。

审阅页从本轮文件生成，输入与输出校验 SHA 后复制到本地 `media/`；无结果时不会回退到旧缓存或远程缩略图。表单和 CSV 默认全部 unreviewed，reviewer 空白。标签绑定 case/job/revision/candidate/rank/SHA；重复状态必须明确选择，不能只凭算法 content_group_id 判断。没有任何真实结果可标注，因此现在不是“已准备好最后签字”的产品。

- 开发审阅：`.cache/meme50/acceptance/20261112-v2/review-development/index.html`
- 留出审阅：`.cache/meme50/acceptance/20261112-v2/review-heldout/index.html`
- 对应 `labels.csv`、`duplicate-groups.csv`、`cases.json` 及 `reproduction-template.json`。
- `comparison/plan.json`：A 关闭/B 开启核验，尚未运行，收益/误导/成本差异没有填写。
- `reproduction/member-template.json`：实际操作者、独立性与 human_attestation 均未签署。

目前三个资源充足案例尚未预筛，40–50 门槛未验证。账号授权后应先完成开发校准与独立预筛，冻结配置，再使用新的独立 attempt 运行留出。不能据热门角色或来源标题假定有 50 个明确相关的不同素材。

## 可直接执行的工具

在仓库目录、Python 3.11 环境运行。每个 `--out` 必须是不存在的新目录。省略 description 才是真正空文字；批跑只把冻结清单的可选 description 传给 API，不传 family、来源或判断备注。

```bash
.venv/bin/python -m scripts.meme50_acceptance probe \
  --image .cache/meme50/inputs/dev-01.gif --out .cache/meme50/acceptance/next-probe

.venv/bin/python -m scripts.meme50_acceptance run-suite \
  --manifest docs/meme50-evaluation-v2.json --split development \
  --base-url http://127.0.0.1:8000 --check-db --local-stack \
  --out .cache/meme50/acceptance/next-development

.venv/bin/python -m scripts.meme50_acceptance review \
  --runs .cache/meme50/acceptance/next-development \
  --out .cache/meme50/acceptance/next-review

.venv/bin/python -m scripts.meme50_acceptance score \
  --manifest docs/meme50-evaluation-v2.json \
  --runs .cache/meme50/acceptance/next-development \
  --labels .cache/meme50/acceptance/next-review/labels.csv \
  --out .cache/meme50/acceptance/next-scores

node scripts/verify_meme50_browser.mjs \
  --base-url http://127.0.0.1:8000 --image .cache/meme50/inputs/dev-01.gif \
  --check-db --local-stack --out .cache/meme50/acceptance/next-browser
```

`--local-stack` 只为本机专用 profile 读取既有受保护连接配置，不打印密码；其他部署去掉它，在当前进程配置自己的 `DATABASE_URL`。不要把地址/凭据写在命令参数或提交到 Git。`DEVICE_TOKEN` 从环境传入浏览器的临时会话，不保存到证据。

probe、score、finalize：0 passed，1 已测失败，2 待授权/人工，3 证据或执行异常。run-suite 的 exit 0 只说明所有机器调用通过，**不代表数量或质量**；已有 verify_meme50 的 0/2/3 语义保留。review 默认返回 2，因为没有自动完成人工判断。冻结输入 SHA、版本、标签绑定或目录保护失败时拒绝，不挑掉失败案例。

最终汇总命令的实际参数记录于 `finalize-invocation.json`，退出状态记录于 `finalize-current-command.log`；示例：

```bash
.venv/bin/python -m scripts.meme50_acceptance finalize \
  --manifest docs/meme50-evaluation-v2.json \
  --probe PROBE/probe.json --runs DEVELOPMENT --runs HELDOUT \
  --development-scores DEVELOPMENT_SCORES/scores.json \
  --heldout-scores HELDOUT_SCORES/scores.json \
  --browser BROWSER/browser-evidence.json \
  --regression REGRESSION.json --reproduction MEMBER_RECORD.json \
  --out NEW_FINAL_DIRECTORY
```

## 最终 A0–A8

机器生成的 [脱敏汇总](evidence/meme50-acceptance-20261112.json) 对应 `.cache/meme50/acceptance/20261112-v2/final-current/final.json`：A7 passed，其余 pending；version_mismatch=false，总状态 pending、exit 2。

最小外部缺项是本机受保护配置内的已授权 Gemini、Google Vision 和 Brave 凭据；之后仍需实际模型/两通道/自动核验联调、三个资源充足案例、开发校准、留出质量与正式网页成功闭环。没有结果前不能请真人签署质量；有结果后再由真人标注并由另一位成员独立复现。执行 agent 没有代填身份、签名或正向结论。
