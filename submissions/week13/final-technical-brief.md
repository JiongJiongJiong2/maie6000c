# 技术总结与复盘

## 产品叙事与技术边界 | Product positioning and technical boundary

产品愿景是帮助中文互联网 meme 进入全球社交表达。当前技术交付提供截图检索、用户主动联网发现、人工确认、原件收藏、离线复用，以及设备支持时的用户主动分享。它尚未实现完整授权的中文 meme 语料、自动文化语境翻译/本地化或向海外社交平台自动发布；这些方向需要独立的产品、版权和平台集成验证。

The product vision is to bring Chinese internet memes into global social
conversations. The current implementation provides screenshot retrieval,
user-triggered online discovery, human review, saving originals, offline
reuse, and user-directed sharing where supported. A comprehensive rights-
cleared Chinese meme corpus, automatic cultural translation/localization, and
automated publishing to overseas platforms are not implemented; each requires
separate product, rights, and platform-integration validation.

## 用户流程和组件

截图可先在本机用多帧视觉向量查找。用户主动续搜后，API 持久化一个关联任务；worker 选择配置的视觉模型提取画面和文字，由 DeepSeek 生成查询并向搜索接口请求网页。媒体获取服务读取公开来源，验字节、解码动画，按实际视觉内容排序和去重。用户确认后保存原件，后台写入多帧索引，新的本地请求即可复用。[架构](../../docs/architecture.md) · [原件与向量数据模型](../../docs/database-and-vector-search.md)

## 工程证据

发布候选在全新的数据库、账户和浏览器会话复验，目标原件在线与离线均位居首位。在线任务耗时 137.846 秒，调用 2 次模型、5 次搜索并尝试 66 次媒体获取。同样的来源线索产生了 4 个动画和 46 张静图，与 PR 阶段的返回构成不同。两个版本均按事先留存的原件核对下载。网页分享已核验到文件准备就绪，手机端最终发送或导入需另行确认。[发布版回执](browser-release-verification.json)

11 月 28 日用 Chromium 系 Chrome 浏览器操作正式页面，初次本地搜索返回空，用户点击继续联网并补充来源线索。HKGAI 识图与 DeepSeek 搜索发布 50 条经解码的媒体，其中 17 个动画。独立参照 GIF 排第 1。联网任务耗时 169.414 秒，共 5 次搜索、2 次模型调用、87 次获取原媒体的尝试。8 帧 × 512 维的收藏索引就绪后，断开外部获取并重启服务；新浏览器以另一帧在离线模式下再次首位命中。单例任务耗时和排名均可追溯到执行回执。[本次工程验证与此前未命中](../../docs/evidence/gif-acquisition/hkgai-web-offline-20261128.json)

从已授权的 12 个参考 GIF 抽帧，只改变索引的帧覆盖范围，多帧比只用首帧多命中一个 Top-3 目标。两组都包括相同的冷启动模型加载。该试验检验库内检索行为，真实用户任意截图的成功率需要独立样本。[逐项结果](local-corpus-evaluation.json)

11 月 28 日的中文 meme 家族留出机器评测共使用 2,622 个唯一文件、1,480 张程序生成的截图变化，完成 2,960 次首帧/多帧检索。普通留出集精确 Top-3 为首帧 20/84、多帧 23/84；紧裁图为 18/21 对 21/21，模拟聊天界面每组仅 1/21，字幕遮挡为 0/21。结果表明模型对边框、遮挡和风格变化仍很脆弱。首轮真人盲评为 60 题、187 组候选，标注仍待完成；这些机器结果不等于真实用户成功率，也不证明素材可自由再发布。[基准方法与限制](../../docs/retrieval-benchmark-at-scale.md) · [机器结果](../../docs/evidence/chinese-meme-retrieval-20261128.json)

此前发布到开发分支的联网任务返回过 48 个媒体，包含 25 个动画，其格式、帧数、下载 SHA 和数据库记录已逐项核对。11 月 27 日的真实 DeepSeek API 实测还覆盖了 44 帧原 GIF、收藏建索引和重启后的离线网页下载。[真实媒体核对](../../docs/meme50-dedup-fix-20261113.md) · [11 月 27 日回执](../../docs/evidence/gif-acquisition/deepseek-offline-reuse-20261127.json)

## 运行中暴露的问题

Windows 账户目录、任务 UUID 和内容哈希共同拉长路径。原子写入曾再次把完整内容哈希拼进临时文件名，导致原文件路径合法而临时文件超限。改为独立随机临时文件名后，仍在目标目录原子替换。PostgreSQL 在东八区会话返回带偏移的时间戳，直接覆盖时区会使任务耗时少算八小时；现在按真实时间差计时。

公开搜索经常返回内容相近的动画、不同分辨率的衍生版或静态图。演示按事前记录的目标 SHA 判定恢复是否成功。模型生成的查询曾丢弃用户给出的出处或动画要求；现在在原查询预算中为这些线索保留位置。一次可复演的工程闭环与独立真实需求评估应各自报告。[评价口径及分工](../../docs/final-closeout-plan.md)

## 发布边界

网页支持原始 GIF 下载。整合的 Web Share 功能依赖设备是否支持分享该文件类型，最终发送需用户在目标应用确认。WhatsApp 导入为独立实验入口，微信、QQ 的客户端差异及实测情况见专项记录。[网页兼容](../../docs/yuanjian-web-compatibility.md) · [WhatsApp 实验](../../docs/whatsapp-web-import-experiment.md) · [微信](../../docs/wechat-gif-sharing-investigation.md) · [QQ](../../docs/qq-import-feasibility.md)

---

# English translation

## User workflow and components

Users can first search the local reference corpus and indexed private-library
GIFs using multi-frame visual vectors. When they explicitly continue online,
the API persists a linked job. The worker uses the configured vision provider
to analyze the image and text; DeepSeek plans queries and searches the web. An
isolated media-fetch service retrieves public sources, validates bytes and
animation decoding, and ranks candidates by their visual content. After user
confirmation, the original is saved and indexed across multiple frames so a
later local request can reuse it. See the [architecture](../../docs/architecture.md)
and [media/vector data model](../../docs/database-and-vector-search.md).

## Engineering evidence

The release candidate was rechecked with a fresh database, account, and
browser. The target ranked first in both online and post-restart offline
search; downloads matched the independently retained original. That online
job took 137.846 seconds, used two model calls and five search calls, and
attempted 66 media fetches. It returned 50 items: 46 static images and 4
animations. The result differed from the PR-stage run. The web share flow was
verified to prepare the file; sending or importing it on a phone still needs
separate confirmation. See the [release receipt](browser-release-verification.json).

On 28 November, the formal page was tested in Chrome with HKGAI vision and
DeepSeek search. The initial local search returned no result; the user
continued online and supplied a source clue. The search returned 50 decoded
media items, including 17 animations. The independently retained 44-frame
target ranked first. The job took 169.414 seconds, used five search calls and
two model calls, and attempted 87 original-media fetches. After the eight-frame,
512-dimensional saved index became ready, the API and worker were restarted
and external access was blocked. A new browser session again ranked the target
first using a different frame. Both downloads were byte-identical to the
1,001,718-byte original. Earlier failed attempts are retained in the
[execution receipt](../../docs/evidence/gif-acquisition/hkgai-web-offline-20261128.json).

For the 12 permitted reference GIFs, multi-frame indexing improved Top-3 from
11/12 to 12/12 when only frame coverage changed. Queries used frames sampled
about one third into each source GIF, and both runs included the same cold
model startup. This checks local-corpus behavior; it does not estimate
success on arbitrary user screenshots. See the [item-level results](local-corpus-evaluation.json).

The 28 November Chinese-meme family-held-out machine evaluation used 2,622
unique files and 1,480 programmatically generated screenshot variants, for
2,960 first-frame and multi-frame searches. Exact Top-3 on the ordinary
held-out set was 20/84 and 23/84, respectively. Tight crops scored 18/21 vs
21/21; simulated light/dark chat interfaces scored only 1/21 each, and
subtitle occlusion scored 0/21. This exposes substantial sensitivity to
borders, overlays, and style changes. The first human blind-review batch
sampled 60 cases and 187 candidate pairs; judgments remain pending. These
machine results are not real-user success rates and do not establish
unrestricted media-republication rights. See the [benchmark method and
limitations](../../docs/retrieval-benchmark-at-scale.md) and
[machine evidence](../../docs/evidence/chinese-meme-retrieval-20261128.json).

Earlier development-branch runs also checked the decoded format, frame count,
download SHA-256, and database records for 48 returned media items, 25 of which
were animated. The 27 November DeepSeek run covered a 44-frame original, saving,
indexing, and offline web reuse after restart. See the
[media verification](../../docs/meme50-dedup-fix-20261113.md) and
[27 November receipt](../../docs/evidence/gif-acquisition/deepseek-offline-reuse-20261127.json).

## Problems found during implementation

On Windows, account-directory names, task UUIDs, and content hashes combined
to create long paths. Atomic writes also appended a full content hash to a
temporary filename, making that temporary path exceed filesystem limits even
when the final path was valid. The implementation now uses an independent
random temporary name and still atomically replaces the destination.

PostgreSQL sessions in a UTC+8 time zone can return offset-aware timestamps.
Overwriting the time zone directly previously undercounted elapsed time by
eight hours; duration calculations now use the actual time difference.

Public search often returns similar animations, resized variants, or static
images. The demo therefore compares candidates against a target SHA recorded
independently. Query planning previously dropped user-provided source or
animation clues; the current budget reserves space for these clues. A single
reproducible engineering workflow and an independent user-request evaluation
must be reported separately. See the [evaluation protocol and ownership](../../docs/final-closeout-plan.md).

## Release boundaries

The web application supports downloading the original GIF. Web Share depends
on the browser and device supporting that file type, and the user must confirm
the final send in the destination application. WhatsApp import is a separate
experiment; client-specific behavior for WeChat and QQ is documented in their
individual reports: [browser compatibility](../../docs/yuanjian-web-compatibility.md),
[WhatsApp](../../docs/whatsapp-web-import-experiment.md),
[WeChat](../../docs/wechat-gif-sharing-investigation.md), and
[QQ](../../docs/qq-import-feasibility.md).
