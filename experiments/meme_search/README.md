# Meme 搜索小实验：发现网页、验证素材、持久化复用

执行日期：2026-10-30（Asia/Shanghai）。基线：`dev@d3db809`。这是独立实验，不改变现有 W07 API、worker、数据库和网页。

后续已实现独立的 [第一版功能页](../../docs/meme-agent-v1.md)，接入真实 DeepSeek 查询规划、模板目录和确认收藏闭环。[MVP 验证摘要](mvp_validation.json) 与下文原始小实验分开记录；下文“未配置 API key”等描述只对应先前的小实验阶段。

**观察结论：这些经典案例里，普通搜索已经能识别梗的家族。专门的查询规则更容易找到明确标注无字模板的页面，但这批小样本不能证明 skill 的普遍效果。真正暴露的问题在下载与素材验证：GIF 页面可以只给出单帧预览，无字图也可能是另一场景或重绘版本。**

本轮使用 8 个助手构造的中文描述、3 种查询，共 24 次真实宿主联网搜索。不是用户研究，不是截图反向搜索，也不是完整产品 agent。两名独立上下文的 GPT-6.1-sol（medium）分别生成普通查询和遵循 meme 流程的查询；GPT-6-luna 做独立标签，主 agent 复核并保留修订记录；GPT-6.1-sol 实现脚本，GPT-6.1-terra 审查测量与代码。没有可用的供应商 API key，因此没有伪造 Brave/SerpApi/MCP 调用结果；skill 流程由提示词传入，未测试运行时自动发现/加载 skill。

## 1. 搜索观察

七个案例有预先指定的目标家族；第八个是存在性未知的描述，单独保留，不当作已证明的负样本。每次只评估工具返回的前五个网页，未根据结果调整查询。七个已知案例均是易描述的经典家族，有明显选择偏差和天花板效应。

| 观测量 | 原始描述 | 普通改写 | meme 流程改写 |
|---|---:|---:|---:|
| Top-5 找到相关家族网页 | 7/7 | 7/7 | 7/7 |
| Top-5 找到明确无字模板页面 | 1/7 | 1/7 | 3/7 |
| Top-5 找到明确动画素材页面 | 1/7 | 2/7 | 2/7 |
| MRR@5（家族网页） | 1.000 | 1.000 | 1.000 |
| 单次搜索工具耗时中位数 | 2.230 s | 2.339 s | 2.446 s |

分母 7 包括不同意图，后两行发现率不等于每种任务的成功率；逐案例标签见 [judgments.json](judgments.json)，分类统计见 [summary.json](summary.json)。按输入中明确要求无字/改字的三个案例（c01、c05、c06）观察，明确无字页面分别出现于 0/3、1/3、2/3；这只是意图切片，不是独立实验。

“相关”包括百科、新闻和模板变体。对照的家族命中与 MRR 完全相同，不能声称 agent 提升了识别准确率。查询语言、别名和用途词同时变化，也无法把任何差异归因于单一规则。每条件只有一次生成与一次检索，无随机种子控制、重复运行、显著性推断。并行调用和宿主缓存会影响耗时；表中不包含 query-planner、下载、验证或用户操作时间。实际美元成本和 token 用量不可见，记为未知，不记作免费。

c08 三组返回了安全帽、聊天、其他梗图或搜索站等结果；没有足够证据确认完整目标。它说明系统需要允许“不确定/未找到”，不能据此断言互联网不存在该图。

## 2. 实际素材探测

从排名内网页选择 7 个公开媒体链接，限量下载、检查 MIME/文件签名并解码全部帧。它们是为检查失败类型而挑选的样例，**不是随机样本，5/7 可下载不能外推成系统成功率**。元数据在 [media_probe.json](media_probe.json)，观察到的链接及来源在 [media_sources.json](media_sources.json)。

| 样例 | 实际结果 | 对需求的含义 |
|---|---|---|
| Drake 无字底图 | JPEG，1200×1200，1 帧；查看画面确认没有新增配字 | 可以作为模板候选；本轮没有实际编辑或用户验收 |
| Two Buttons 模板 | WebP，1024×1536，1 帧，无字 | 页面说明且画面显示为重绘版本，不能当作原漫画找回 |
| 王境泽“真香 GIF”预览 | 文件格式 GIF，但只有 **1 帧**，带“真香”字幕 | 不满足下载可播放动画的需求 |
| 王境泽“空白表情 GIF”预览 | JPEG，350×287，1 帧，无字幕 | 属于同人物的指人场景，不是端碗吃饭的完整动画 |
| 张学友表情预览 | GIF，160×160，24 帧；带字幕且模糊 | 确实会动，但不是用户要求的无字高清底图 |
| 熊猫头候选一 | 域名解析/URL 检查失败 | 没拿到素材，不能按网页标题计成功 |
| 熊猫头候选二 | 网络或 TLS 失败 | 没拿到素材；没有关闭证书校验重试 |

另一个无字熊猫头搜狐页面，宿主抓取失败、本机请求返回 HTTP 403，未继续绕过。SOOGIF 页面明确将高清无水印版本放在登录之后；本轮只测公开预览，不登录或绕过限制。下载可用不等于拥有改编或共享授权，没有将这些素材发布为共享库。素材与原始网页工具返回全文只在忽略目录 `.cache/meme-search-pilot/`；仓库只提交网址、哈希、测量与自行撰写的说明。

## 3. 入库与第二次检索 smoke

用现有离线 CLIP 编码器对 5 个成功解码样例的第一帧生成真实 512 维特征，在实验专用 SQLite 中保存向量。另启一次进程重复摄取，再另启进程读取库，对每张图在内存缩小到 75% 后重新编码，以余弦相似度排序。

首次从 0 写入 5 条；再次写入新增 0 条、仍为 5 条；两个失败下载不入库。第二次检索的 5 个近重复查询均在 Top-1 找到对应素材，SQLite 文件哈希在重复摄取和只读检索后保持一致。结果见 [首次摄取](reuse_ingest_first.json)、[重复摄取](reuse_ingest_repeat.json)、[重新检索](reuse_query.json)。

这只证明本机**持久化、幂等摄取、重新编码和检索**链路可行。查询来自已入库图的缩放版本，样本只有五个；不是独立准确率，也不是中文语义检索、跨用户权限或 PostgreSQL/pgvector 集成验证。GIF 这里只取第一帧。只有格式合格的样例进实验库，并没有把它们认定为产品上“用户接受/允许共享”的素材。

## 4. 下一步实施决策

下一阶段优先实现“候选页面 → 媒体解析 → 解码/多帧/无字/同版本检查 → 用户确认”，再接正式摄取队列。建议先做少数来源适配器，返回原图、预览、静态/动画、是否需登录和失败原因，避免把一个 URL 直接视作可入库素材。

编辑先支持已确认的无字静态模板；保存模板与成品关系。任意 GIF 去字不进入首版验收。共享索引沿用现有数据库设计，来源使用权限和用户可见性另行处理。本实验尚未实现编辑器、用户确认 UI 或共享服务。

接着收集 30–50 个真实截图，由人标注目标原图/动画或“无法确定”，保持同一调用预算，比较关键词、反向图搜、来源适配与重排。需要有效的供应商凭据，才能测独立部署的自动调用、MCP 接入以及实际费用。本轮结果支持继续做这个验证，不支持承诺任意中文截图都能找回。

## 5. 复现

从仓库根目录执行。Python 3.11，基础探测依赖项目已有 `httpx`、`Pillow`；统计只读 JSON；向量 smoke 还依赖项目 retrieval extras 和已准备在 `data/models/clip-vit-base-patch32` 的固定版本权重。脚本不会自动下载模型。下例在当前 Windows 环境已执行；其他系统把解释器路径替换为对应虚拟环境 Python。

```powershell
.venv/Scripts/python.exe -m pytest experiments/meme_search/tests -q
.venv/Scripts/python.exe -m ruff check experiments/meme_search
.venv/Scripts/python.exe experiments/meme_search/pilot.py summarize --runs experiments/meme_search/runs.json --judgments experiments/meme_search/judgments.json --out .cache/meme-search-pilot/recomputed-summary.json
.venv/Scripts/python.exe experiments/meme_search/pilot.py probe --urls experiments/meme_search/media_sources.json --out .cache/meme-search-pilot/reprobe.json --cache-dir .cache/meme-search-pilot/media
```

重新探测可能因源站变化产生不同结果。用**新的数据库文件名**建立本次媒体结果的向量 smoke；这样不会把旧候选混进排名。已保存实验输出不要覆盖，用 `.cache` 输出新结果。

```powershell
.venv/Scripts/python.exe experiments/meme_search/reuse_smoke.py ingest --probe .cache/meme-search-pilot/reprobe.json --cache-dir .cache/meme-search-pilot/media --db .cache/meme-search-pilot/reuse-new.sqlite --out .cache/meme-search-pilot/ingest-new.json
.venv/Scripts/python.exe experiments/meme_search/reuse_smoke.py ingest --probe .cache/meme-search-pilot/reprobe.json --cache-dir .cache/meme-search-pilot/media --db .cache/meme-search-pilot/reuse-new.sqlite --out .cache/meme-search-pilot/ingest-repeat.json
.venv/Scripts/python.exe experiments/meme_search/reuse_smoke.py query --probe .cache/meme-search-pilot/reprobe.json --cache-dir .cache/meme-search-pilot/media --db .cache/meme-search-pilot/reuse-new.sqlite --out .cache/meme-search-pilot/query-new.json
```

**离线可重算统计，普通 Python 不能直接重放宿主的联网工具。** 重新检索需在有 `web.search_query` 的 agent 环境逐条执行 [queries.json](queries.json)，遵循冻结的 [protocol.md](protocol.md)，每条 query 一次、`response_length=long`、不带站点/时间过滤，记录前五个正常网页及每次调用起止时间。不要把摘要脚本称为自动搜索 agent。原始响应本机可审计，但未将第三方全文推送；公开的 [runs.json](runs.json) 保留查询、顺序、标题、网址和捕获时间。

证据文件包括独立原始标签、复核标签和最终 adjudication；`capture_manifest.json` 保存冻结协议/查询与本机 raw 的 SHA-256。哈希用于完整性核查，不是时间公证。`validation.json` 记录本轮实际检查。

探测器只适合这批明确选择的公开链接：限制 HTTP(S)、公共解析地址、重定向、5 MiB 响应、500 帧和解码像素量。DNS 预检与底层请求会分别解析，仍有 DNS rebinding 窗口；15 秒是协作式预算，不能替代生产环境的出站网络隔离和进程硬超时。
