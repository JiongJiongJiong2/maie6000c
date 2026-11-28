# MemeRetrieve · W13 产品交付

团队成员为 Jiongle He、Haoxuan Jiang、YuanJian Li、Zirui Huang。产品用一张截图寻找原始动态 GIF，并支持将选中的原件收藏到私人库，下次在本机再次检索。[项目分工](../../docs/final-project-plan.md)

## 产品叙事与实现边界 | Product positioning and scope

**愿景：**帮助中文互联网 meme 跨越语言和平台边界，进入全球社交表达。产品希望让海外用户更容易发现、理解并使用具有中文互联网文化背景的 meme。

**当前交付：**截图检索、本地/联网候选发现、人工审核、原件收藏和离线复用；支持的设备可通过系统分享面板由用户选择分享目标。当前小规模参考语料不是完整的中文 meme 资源库，产品也尚未实现自动文化解释/翻译或向海外社交平台自动发布。上述能力应视为后续产品方向，而非本次验收结论。

**Vision:** Connect Chinese internet memes with global social conversations,
helping people discover, understand, and reuse culturally specific
expressions across language and platform boundaries.

**Delivered today:** Screenshot-based retrieval, local and user-triggered
online discovery, human review, saving the original, and offline reuse. On
supported devices, users can choose a destination through the system share
sheet. The small reference corpus is not a comprehensive Chinese meme library;
automatic cultural explanation/translation and publishing to overseas social
platforms are not implemented and remain future product work.

## 运行与演示

在 Python 3.11 环境准备 12 个基线参考 GIF、固定版本的 CLIP 权重和多帧索引，首次启动时执行数据库迁移。可选地加入四个中文 meme 本地示例用于演示；它们的逐项来源和素材使用限制见[示例清单](../../docs/demo-evaluation-examples.json)。Windows 可用本机 PostgreSQL 16 启动器，也可以使用 Docker PostgreSQL 配合主机 worker。[安装与启动](../../docs/local-demo.md) · [数据库与持久卷](../../docs/database-and-vector-search.md)

联网演示需要一个视觉供应商和 DeepSeek。HKUST 为默认选项；使用 HKGAI 时，在项目虚拟环境运行 `python -m scripts.configure_meme50 --provider hkgai --vision-only`。DeepSeek 查询规划和网页搜索共用项目的 DeepSeek 配置。用 `python -m scripts.configure_meme50 --check` 核对当前选择，再启动服务。每位部署者使用自己的授权凭据。[供应商运行说明](../../docs/hkust-deepseek-execution.md)

1. 打开 `/web/`，在启用账户的安装上登录，选择、拖入或粘贴截图。可点击 **Crop screenshot** 框选 meme 并确认，也可保留整图。若本地演示配置了示例库，可从首页选择一个固定示例；该演示快捷入口和账户私人库是不同功能。选择仅本地检索并保留结果。
2. 当本地结果中缺少目标时，从同一页面点击继续联网搜索，描述画面、动作或记得的出处。网页创建与原始请求关联的新任务。
3. 筛选动画，播放并下载识别出的 GIF。演示前独立保存目标文件的 SHA-256，用它核对下载内容。
4. 点击确认并收藏，等到索引显示就绪。保留数据库、媒体和模型目录，重启 API 与 worker。
5. 在新浏览器会话中登录原账户，禁用对外联网，选择仅本地检索并上传另一帧。检查收藏资产、命中位置和第二次下载的 SHA-256。

## 可复核的证据

随后在已整合分享和兼容改动的发布候选 `48f7693` 上，从空账户再次完成正式网页验收。目标 GIF 联网和重启离线均排第 1，两次下载与独立原件逐字节相同。该次 50 条结果包含 46 张静图和 4 个动画，网页筛选数与数据库一致。联网候选卡和离线收藏卡均成功为系统分享菜单准备原 GIF。[发布版实际任务与下载回执](browser-release-verification.json)

11 月 28 日从正式 Chrome 页面用 HKGAI 和 DeepSeek 找回 Wikimedia Commons 的 44 帧地球 GIF。用户给出了来源站点和画面描述，两个搜索请求分别用了不同抽帧。目标联网第 1，确认收藏后索引就绪，重启服务并禁用外联后本地第 1。网页的两次下载与独立留存的 1,001,718 字节原件逐字节一致。回执保留了成功之前六次尝试中遇到的路径故障与原件未命中。[正式网页回执](../../docs/evidence/gif-acquisition/hkgai-web-offline-20261128.json)

固定参考库的 12 个 GIF 在同一阈值 `0.82`、同一模型、同一组输入下，首帧索引 Top-3 为 11/12，多帧索引 Top-3 为 12/12。输入取自每个源 GIF 约三分之一处的帧。逐项 SHA、帧号、得分与实际耗时在结果文件中。[本次本地运行](local-corpus-evaluation.json) · [评估方法](../../docs/yuanjian-benchmark-guide.md)

### 截图裁切与本地 meme 示例

网页现允许用户在提交前裁切并确认截图；同一裁图用于本地检索和后续联网搜索。单独的离线实验在合成聊天界面截图上对比整图、像素自动裁切和已知生成框：三类界面库内精确 Top-3 分别为 2/63、41/63、52/63。自动裁切也将库外返回任意候选从 0/339 增至 290/339，说明召回提升伴随误返回风险，需用户检查候选。实验没有真实聊天截图，也没有真人误选标注；自动定位器的离线成绩不能等同于当前手动裁切交互或真实用户命中率。[裁切实验](../../docs/chat-screenshot-crop.md) · [运行证据](../../docs/evidence/chat-screenshot-crop-20261128.json)

本地演示首页另可加载四个固定中文 meme 示例。四张输入经本地 API 和 worker 检索后，Top-1 下载均与清单中 GIF 原件的 SHA-256 匹配（4/4）。这是固定示例流程检查，不是独立准确率评估；多项来源的再发布授权仍未确认，示例仅用于本机课程演示。[验收回执](../../docs/evidence/home-example-retrieval-20261128.json) · [来源与使用条件](../../docs/demo-evaluation-examples.json)

### 中文 meme 家族留出评测 | Chinese-meme family-held-out evaluation

11 月 28 日新增的库内机器评测使用 2,622 个唯一文件和 1,480 张程序生成的截图变化，共完成首帧、多帧 2,960 次检索。普通家族留出集的精确 Top-3 为：首帧 20/84，多帧 23/84。聊天界面类和字幕遮挡类表现很弱，不能据此声称真实社交媒体截图已可靠解决。

The 28 November in-library machine evaluation used 2,622 unique files and
1,480 programmatically generated screenshot variants, completing 2,960
first-frame and multi-frame searches. Exact Top-3 on the ordinary
family-held-out set was 20/84 for first-frame indexing and 23/84 for
multi-frame indexing. Chat-interface and subtitle-occlusion categories
performed poorly; these results do not establish reliable recovery on real
social-media screenshots.

专题 meme 家族检索属于开发诊断，并非独立验收；首轮人工盲评仅抽取 60 道题、187 组候选，真人标注结果仍待完成。该评测衡量的是固定素材库内检索，不是联网搜索，也不证明这些素材可自由再发布。逐项数据、素材边界和方法见[基准报告](../../docs/retrieval-benchmark-at-scale.md)及[机器证据](../../docs/evidence/chinese-meme-retrieval-20261128.json)。

Theme-focused meme-family searches are development diagnostics, not
independent acceptance results. The first blind-review batch sampled 60 cases
and 187 candidate pairs; human judgments are still pending. This evaluates
retrieval within a fixed corpus, not online search, and does not establish
unrestricted rights to republish the media. See the [benchmark report](../../docs/retrieval-benchmark-at-scale.md)
and [machine evidence](../../docs/evidence/chinese-meme-retrieval-20261128.json)
for item-level results, corpus boundaries, and methods.

联网搜索还增加了一个受限的空结果补救：若搜索返回零条可用来源、尚无候选，且用户线索与已执行查询包含“哈吉米/哈基米”之一，系统可在原查询预算内改写一条待执行查询。它保留用户否定语境、动作字幕及来源线索；目前有条件测试覆盖，独立截图上的召回收益尚未验证。[实现与评测边界](../../docs/nlp-multi-agent-evaluation.md)

Online search also has a bounded empty-result recovery. If a search returns
no usable sources and no candidates exist, and both the executed query and
user-provided evidence contain one of “哈吉米/哈基米”, one pending query may
be revised within the existing budget. User negation, action/caption clues,
and source hints are preserved. Conditional tests cover the behavior; its
recall benefit on independent screenshots has not been validated. See the
[implementation and evaluation boundary](../../docs/nlp-multi-agent-evaluation.md).

[技术总结](final-technical-brief.md)记录工程验证和检索局限。[AI 使用说明](ai-use-statement.md)记录模型职责及验证方式。独立用户截图的真实命中率、其他成员的复现签字，以及课程平台的提交回执由团队另行确认。

## pgvector 与产品部署

已验证原账户库的逻辑恢复、旧收藏回填、固定参考库 96 帧同步，及跨账户隔离。使用正式网页收藏一份 44 帧 GIF，重启和断网后通过 pgvector 在第 1 名找回，下载文件与原件逐字节一致。移除一条旧收藏的派生向量后，NPZ 回退找回同一资产。公共参考库另用 Noto 样例验证第 1 名、原件下载和无候选三种状态。 [迁移、离线与下载回执](pgvector-verification.json) · [产品使用与 Docker 部署](../../docs/product-deployment.md)

## English | English summary

### Product vision, scope, and demo

The product vision is to connect Chinese internet memes with global social
conversations, making culturally specific expressions easier to discover,
understand, and reuse across language and platform boundaries. The current
verified implementation provides screenshot retrieval, user-triggered online
discovery, human review, saving, offline reuse, and user-directed sharing
where supported. It does not yet provide a comprehensive Chinese meme corpus,
automatic cultural localization, or automated publishing to overseas
platforms; those are future product directions, not acceptance claims.

MemeRetrieve recovers an original animated GIF from a screenshot and lets the
user save it to a private library for later offline reuse. The formal web
application is served at `/web/`. The [team plan](../../docs/final-project-plan.md)
records ownership; its dated plan should not be read as the latest status.

Prepare Python 3.11, the 12 permitted reference GIFs, the pinned CLIP weights,
and the multi-frame index. Apply database migrations before starting the
application. On Windows, use either the native PostgreSQL 16 launcher or
Docker PostgreSQL with a host worker. See the [setup guide](../../docs/local-demo.md)
and [database design](../../docs/database-and-vector-search.md).

Online search requires a configured vision provider and DeepSeek. HKUST is the
default vision option; HKGAI can be selected explicitly. Use the
[provider guide](../../docs/hkust-deepseek-execution.md) and each operator's
own authorized credentials.

1. Sign in at `/web/`, choose **Local only**, and submit a screenshot.
2. If the target is missing, choose **Continue online** and describe the
   scene, action, or known source.
3. Inspect and play the returned animation. Compare the downloaded bytes with
   an independently retained original using SHA-256.
4. Choose **Confirm and save** and wait for index readiness. Preserve the
   database, media, and model directories while restarting the API and worker.
5. Sign in again, disable external access, and search using another frame.
   Verify the same saved asset and compare the second download's SHA-256.

### Reproducible evidence

On release candidate `48f7693`, a fresh account and browser completed the web
workflow. The target ranked first both online and after restart in offline
search; both downloads were byte-identical to the independent original. The
50-result run contained 46 static images and 4 animations. The web filter
matched the database count, and both online-candidate and offline-library
cards prepared the original GIF for the system share menu. See the
[release receipt](browser-release-verification.json).

On 28 November 2026, Chrome was used with HKGAI and DeepSeek to recover a
44-frame Earth GIF from Wikimedia Commons. Two searches used different
source-image frames. The original ranked first online; after confirmation,
indexing, restart, and blocking external access, it ranked first in offline
search. Both web downloads matched the independently retained 1,001,718-byte
original exactly. The receipt also records six earlier failed or unsuccessful
attempts. See the [formal web receipt](../../docs/evidence/gif-acquisition/hkgai-web-offline-20261128.json).

On the fixed 12-GIF reference corpus, at threshold `0.82` and with the same
model and query frames, first-frame indexing achieved Top-3 on 11/12 inputs,
while multi-frame indexing achieved 12/12. Queries used frames sampled about
one third into each source GIF. This is a fixed-corpus engineering comparison,
not a large-scale or independent-user evaluation. See the
[run results](local-corpus-evaluation.json) and
[evaluation method](../../docs/yuanjian-benchmark-guide.md).

The [technical brief](final-technical-brief.md) summarizes implementation
evidence and limitations. The [AI-use statement](ai-use-statement.md)
describes model responsibilities and verification. Retrieval success on
independent user screenshots, reproduction sign-offs from the other team
members, and the course-platform submission receipt still require team
confirmation.

### Screenshot crop and local meme examples

The web client now lets users crop and confirm an image before submission;
that same image is used for local search and any subsequent online search. A
separate offline experiment compared whole-image search, pixel-based
auto-cropping, and the known synthetic box. For three synthetic chat-interface
categories, exact in-library Top-3 was 2/63, 41/63, and 52/63, respectively.
Auto-cropping also increased out-of-library queries returning any candidate
from 0/339 to 290/339, so the recall gain carries false-return risk and needs
human review. The experiment included no real chat screenshots or human
misidentification judgments; its automatic detector results are not the same
as the current manual crop UI or real-user success. See the
[crop experiment](../../docs/chat-screenshot-crop.md) and
[run evidence](../../docs/evidence/chat-screenshot-crop-20261128.json).

The local demo can additionally load four fixed Chinese-meme examples. All
four Top-1 downloads matched their listed original GIF SHA-256 through the
local API and worker (4/4). This is a fixed example-flow check, not an
independent accuracy evaluation. Republication rights remain unverified for
multiple sources, so these examples are for local course demonstration only.
See the [acceptance receipt](../../docs/evidence/home-example-retrieval-20261128.json)
and [source/use conditions](../../docs/demo-evaluation-examples.json).

### pgvector and deployment

Verification covered logical restoration of the original account library,
backfilling saved assets, mirroring 96 reference frames, and account
separation. A 44-frame GIF saved through the formal web application was found
first after restart and network disconnection, with a byte-identical download.
After a derived vector was removed, NPZ fallback found the same asset. Noto
examples separately checked first-place retrieval, original download, and
no-candidate behavior. See the
[migration and offline receipt](pgvector-verification.json) and
[product deployment guide](../../docs/product-deployment.md).
