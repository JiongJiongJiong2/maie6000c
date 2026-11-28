# MemeRetrieve 截图找回原 GIF 评测协议

本协议提出两项独立评测。库内评测回答目标已入库时，多帧索引能否从一张截图找回原件。公开网页评测回答目标未入库时，正式联网流程能否交付准确、可下载的原 GIF。公开网页结果分别报告已知目标的授权素材和真实用户截图。

早期回归使用 12 个固定库 GIF 的抽帧，首帧 Top-3 为 11/12，多帧为 12/12。两次记录完整的在线成功都使用同一份地球 GIF、不同抽帧和明确的 Commons 来源线索，耗时约 138 秒和 169 秒。下列真实用户和开放网页评测的规模、费用、时间上限均为拟定值。[W13 技术总结](../submissions/week13/final-technical-brief.md)

## 11 月 28 日的批量结果

2,622 个唯一文件中有 342 个动图、2,280 张静图。1,480 张派生截图分别用首帧、多帧检索，共 2,960 次运行全部完成。普通题使用含 168 个 GIF 和 1,412 张静图的索引，其余素材按家族留出；指定专题题搜索全部 2,622 份素材。下面的命中标准为前三名中出现与目标 SHA-256 相同的文件。[机器成绩、分组明细与清单哈希](evidence/chinese-meme-retrieval-20261128.json)

| 普通库内留出集 | 首帧 Top-3 | 多帧 Top-3 |
| --- | ---: | ---: |
| 紧裁表情 | 18/21 | 21/21 |
| 模拟浅色聊天界面 | 1/21 | 1/21 |
| 模拟深色聊天界面 | 1/21 | 1/21 |
| 模拟字幕遮挡 | 0/21 | 0/21 |
| 合计 | 20/84 | 23/84 |

这 84 题来自 6 个素材分类的 21 个 GIF。56 题取自多帧索引未采样的源帧，多帧命中 15/56，其余 28 题命中 8/28。带边框或遮挡的三组各自也改变了缩放、压缩等因素；真实聊天截图上的裁切收益需要另测。留出的 452 个库外查询里，两种方法都对 107 个查询返回过其他候选，424 个查询来自同一个 happycat 素材分类。返回了相近候选与用户最终误认原件是两件分别记录的事。

指定专题为开发诊断题。多帧精确 Top-3 在动态哈基米、奶龙、美团袋鼠上分别为 5/20、12/48、2/8。静态哈基米为 3/12，静态奶龙为 6/24。每组均按每个文件四种变化计数。全批返回 2,082 个候选位置，跨方法按同题同文件合并后为 1,203 个待核对组合；首轮人工盲评抽取 60 题、187 对。独立真人成绩等待实际标注。另已冻结 3 个不同开发家族的网页先导题，这次运行的供应商调用数为零。

## 复现中文图库实测

在仓库根目录使用项目的 Python 3.11 检索环境。首次需要固定版本萌芽源码包（145,827,238 字节），补充专题另有 19 个社区 GIF（18,942,666 字节）。本机已缓存素材与 CLIP 权重。萌芽 51 个分类共 2,648 个文件，完全相同的文件剔除 45 个，逐帧解码得到 323 个唯一动画、2,280 个静图。专题清单记录 5 个哈基米猫梗、12 个奶龙以及 2 个社区标作美团袋鼠「肥嘟嘟」的动画。专题只用本机副本，逐项来源及第三方权利状态可查。这些标签没有衡量全网热度。[专题来源](chinese-meme-theme-sources.json)

```powershell
$py = '.venv/Scripts/python.exe'
curl.exe -fL https://codeload.github.com/shumengya/meme-api/zip/d452126069915ee401a125227081cb7ba7ece4b3 -o .cache/meme-api-d452126.zip
& $py -m scripts.prepare_chinese_meme_corpus .cache/meme-api-d452126.zip .cache/chinese-meme-corpus
& $py -m scripts.add_retrieval_themes .cache/chinese-meme-corpus docs/chinese-meme-theme-sources.json
& $py -m scripts.benchmark_gif_retrieval --source-manifest .cache/chinese-meme-corpus/gifs-with-themes.json --distractor-manifest .cache/chinese-meme-corpus/stills.json --focus-family 哈基米 --focus-family 奶龙 --focus-family 美团袋鼠 --output-dir .cache/meme-eval-cn
& $py -m scripts.prepare_retrieval_review .cache/meme-eval-cn .cache/meme-eval-cn-review --max-cases 60
```

复跑时给测试与评审包指定新的输出目录。专题文件已有本地副本时，可为 `add_retrieval_themes` 加 `--from-cache .cache/chinese-meme-supplement`。补充专题的素材本身只保存在忽略的缓存目录。普通测试按素材家族留出一批目标，观察能否拒绝相似结果。专题正例则将 2,622 个文件全部放入候选池，并分别计分静图和动图。每个目标导出四种输入（裁剪、明色界面、暗色界面、模拟字幕遮挡）。这些界面和遮挡文字为程序生成，真实中文聊天截图及用户判断另收。对照组分别取首帧或最多八帧，查询图和模型相同，沿用 0.82 阈值。

程序保留每次检索的原始排名及目标 SHA。评审时合并两组候选，按内容去重后只展示匿名截图、参照、候选；无结果也计入机器报告。为当天的人工工作按专题、两种方法是否分歧、是否首位命中分层取最多 60 道题，保留部分正确结果作核查。这个队列适合查错，全体自动成绩用完整题集统计。[NIST TREC 的候选池做法](https://trec.nist.gov/howto.html) · [打开 Label Studio 与导出](retrieval-label-studio.md)

## 样本与运行矩阵

| 评测 | 首轮规模 | 扩容方式与对照 |
| --- | --- | --- |
| 库内精确找回 | 32 个在库目标，每个生成清洁留帧和扰动截图各一张，另加 8 张库外近似图或普通截屏 | 扩至 128 个目标家族和 32 个库外截图，128 个目标放入至少 256 个真实授权 GIF 的固定库。首帧与八帧共用同一编码器、阈值、目标与干扰库。阈值只用开发集定。 |
| 公开网页，已知目标 | 先用 3 个授权样本走通完整任务，扩到 12 个独立家族 | 扩至 30 个独立家族，至少跨三个可说明的内容类别。目标 GIF 或同内容版本均从本地移除。主条件只给图，单独测同一截图加自然描述，再按预算抽样测加站点提示的影响。 |
| 公开网页，真实截图盲测 | 先收 5 个真实需求，确认提交体验和隐私处理 | 按提交先后收至少 30 个真实需求。提交者可给自然提示，目标如能独立确认则归已知组。目标未知的案例记录用户能否用上结果和有无目标确认，单列分母。 |

库内的清洁与扰动输入选自预先固定的 GIF 时间点，尽量避开八帧入库所用帧，优先避开像素重复帧。短 GIF 无独立留帧时标记 `indexed_frame_overlap` 并单列结果。确定性扰动从裁边、缩放、压缩、贴字中分配，记录种子和参数。库外负例在入库清单核验缺席后才纳入，优先挑同角色、相近构图或相近字幕，单报误返回率。登记底层动画、同模板换字、循环裁剪和重编码关系，按整个家族分成开发集和最终验收集。后续真实用户试验可预留约六成家族作留出集。此次混合图库实际按 24 个动画分类家族划分，8 个家族进入留出集。分类及已知别名只是底层模板家族的近似，尚未逐张人工确认跨分类近似项。目标出现在固定索引里是库内任务的前提，留出的是查询家族的调参与评测记录。

网页测试用两份清单。运行清单只含随机 case ID、清理元数据后的图、可见描述和条件。答案清单另由留出集保管人持有，保留目标 GIF、SHA-256、来源页和独立确认记录。禁止把来源 URL、文件名、目标标题、素材页文字或目标哈希放入查询、命名、预热缓存或下载回退路径。自然描述由只看截图的人写。若用户确实记得来源，按真实提示条件报告，来源提示条件只给站点或平台类别。预先固定照片、表情或插画等分层和随机种子，从符合授权与格式的集合抽样，保留被剔除的数量与原因。源站独立检查发现文件在冻结后已下线时保留原案例并标出来源状态。

真实截图只收提交者同意使用的裁剪图。去掉聊天正文、昵称和头像等无关信息，提交者单独同意后才把裁剪图发送给视觉供应商。先锁定所有输入和目标状态，评审只看打乱的候选。若未知目标后来凭独立来源找到原件，把它记为补充结果，保留最初的目标未知分母。

## 低人工成本的素材准备与判分

中文网络表情首选萌芽表情包图库。维护者公布 51 个分类、约 2,600 多张混合 WebP/GIF 表情，并提供完整 JSON 清单和可直接获取的文件。用清单登记分类和路径，固定上游版本后只选能实际解码为多帧 GIF 的文件，计算 SHA-256，按底层动画和近似内容去重后报告实得数量。代码为 MIT，维护者标注 `public/meme/` 素材为 CC BY-NC-SA 4.0，保留署名、非商用和同方式共享条件，另有第三方权利疑问的样本留作待核。站点缩放版只能作「图库公布版本」的字节真值，找到可验证的原始源文件后才能标为原始母版。批量导入库内测试用固定语料，网页组只把对应文件用作隔离答案。Noto 的逐项 GIF 可作为现有 12 项回归对照，该系列为 CC BY 4.0，无官方整套下载入口。[萌芽官方仓库与 API 说明](https://github.com/shumengya/meme-api#readme) · [公开清单](https://meme.smyhub.com/memes.json) · [素材许可](https://github.com/shumengya/meme-api/blob/main/ASSET_LICENSE.md) · [Google 官方目录](https://googlefonts.github.io/noto-emoji-files/?view=docs) · [现有 12 项清单](demo-corpus.json)

开放网页的已知目标首选 Wikimedia Commons 动画 GIF 分类。从 `categorymembers` 取文件页，使用 `imageinfo` 查询原件 URL、大小、MIME 和逐项授权元数据。预筛原创或授权清楚的 CC0、公有领域、CC BY 或 CC BY-SA 项，逐项保留授权、作者、来源和版本。例示的地球原件由文件页标为 400×400、约 978 KB、44 帧，页上列有 CC BY-SA 3.0。批量获取前缓存元数据、使用可识别的 User-Agent，执行源站约束。下载后以真实 GIF 解码排除静态图，并以本项目媒体字节和像素限制筛样。若样本只有 Commons，结果标为 Commons 授权目标的公开搜索表现。[Commons 分类](https://commons.wikimedia.org/wiki/Category:Animated_GIF_files) · [分类 API](https://www.mediawiki.org/wiki/API:Categorymembers) · [文件 API](https://www.mediawiki.org/wiki/API:Imageinfo) · [复用规则](https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia) · [User-Agent 规则](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy) · [地球原件文件页](https://commons.wikimedia.org/wiki/File:Rotating_earth_(large).gif)

TGIF 作者发布约 10 万个 Tumblr GIF 的 URL 与约 12 万条描述，README 将使用范围限定为获准的非商业研究，发布物提供链接。逐项确认媒体可用性和授权后可补国际素材。首轮用萌芽扩中文网络梗图覆盖，并用 Commons 补逐项许可清楚的源文件。[TGIF 作者发布](https://github.com/raingo/TGIF-Release#readme)

精确评分无需逐条人工标注。用产品下载入口取得候选字节，GIF 实际解码须超过一帧，且 SHA-256 与预先冻结的目标相同才记精确命中。对不同 SHA 的文件，用合成后帧序列、帧时长及循环信息检测可自动确认的等价编码。只把可能等价的前几条、盲测用户接受的候选和随机抽取的未命中案例交给人看，按同一动画的技术变体、同模板或同场景、无关分别记录。筛选用的感知哈希相似性本身不足以认定等价。仅找到网页、静态帧或同款替代时分别留证据。公开结果保留哈希和许可允许的素材，用户截图按同意范围访问。

人工判分复用自托管 Label Studio Community。评审任务 JSON 只含随机 `case_id`、截图和匿名候选文件引用，素材通过本地存储加载。用解码出的代表帧拼图快速筛选，再打开原 GIF 核实疑似动画，导出 JSON 后按 `case_id` 合并回分数。单机离线可用 Oxford VIA 的单 HTML 版或 LISA 批量浏览媒体。评审界面隐藏查找方法和目标来源，真值清单仅由汇总端读取。素材与标注留在本机评测目录。[Label Studio 开源仓库](https://github.com/HumanSignal/label-studio) · [本地存储文档](https://labelstud.io/guide/storage.html) · [Oxford VIA](https://www.robots.ox.ac.uk/~vgg/software/via/)

## 运行与统计

固定初始库、代码 SHA、编码器、供应商、配置指纹、清单哈希、测试窗口和采样种子。对比组交错运行，使用独立请求和空私库，冻结缓存策略且不在发现阶段收藏。A 只跑本地检索，B 在相同本地设置下用固定规则提交原始描述或共同 OCR 词，C 使用同等输入与预算的查询规划和补搜。B/C 的搜索来源、查询次数、页面和下载上限、候选排序及超时必须一致，实际用量各计。若要衡量规划本身，共用视觉事实、OCR、媒体验证和重排；若要衡量正式产品，总体结果单列，解释各组启用的模块。产品有「动画」筛选，先报默认顺序 Top-1/Top-3，再单报动画筛选后的 Top-3。收藏后复用另测，至少选不同帧、重启后断网查询并核对原件 SHA。

先跑单 worker 串行开发样本，避免在供应商不健康时消耗完整留出集。正式 `meme50-v2` 默认请求 50 条，当前任务上限为 3 次模型、16 次搜索、120 次原媒体获取、40 个页面，初始超时 180 秒且总上限 300 秒。评测正式产品用相同参数，首轮将 3 个作业的搜索请求上限记为 48 次。若 12 个 case 各跑一次正式配置，上限 192 次搜索，按 DeepSeek 官方每千次成功的直接 Search API 请求 0.75 美元估算，搜索部分最多约 0.144 美元。模型、视觉服务、网络以及额外对照条件另计。设置整批次数和金额上限，记录各 provider 的调用及 token 用量。两个连续 401、403 或 429 时暂停新增任务，保留首轮结果，恢复后明确区分补跑批次。完整作业用现有稳定超时，不为追赶检查点人工取消并删掉未命中。[项目预算及供应商](hkust-deepseek-execution.md) · [DeepSeek 官方接口和计费](https://api-docs.deepseek.com/guides/search/)

每组报告目标已知样本精确 Top-1、Top-3 的 `k/n`，以及等价动画、同款替代和成功下载率。目标未知组报告确认人数、用户接受率和未解决数量。失败留在已知样本分母，分别给出索引或本地候选缺席、搜索未发现目标来源、发现来源但未提取媒体、原件抓取失败、解码失败、已获目标但排名未进前 K、服务错误或预算耗尽。只有 trace 能定位阶段时才归因，否则记未能定位。保存服务耗时与用户端耗时，分别记录排队、首个可用预览、列表完成和下载验证时间，报告 p50/p95 及达到上限的数量。小样本先给计数，扩容后在同一组内按家族做配对重采样区间，避免把同源截图当多个独立证据。

## 仓库复用与 17:30 检查点

`services.retrieval.evaluate_local` 可先复跑固定库对照，本轮批量工具已接入同一 CLIP 编码和 `rank_assets`，按冻结清单运行普通与专题测试。`scripts.meme50_acceptance run-suite` 可串行运行同一正式联网配置并保存经下载核验的结果，输入清单按脚本的 `case_id`、`family` 和 `development/heldout` 字段准备。该脚本现用无账户流程或设备令牌，若在启用账户的 Compose 实例调用，需要登录会话；首轮可在独立回环评测栈使用现有无账户模式。脚本覆盖直接联网入口。本轮新增的网页先导工具可按 SHA 核对下载文件。正式网页先本地再续搜及 `A/B/C` 的等预算控制仍需独立对照。既有 `services.retrieval.benchmark` 只汇总人工确认的真实截图，且限制 2 搜索、2 规划、6 下载、3 候选。保留它用于既定窄预算协议，大批派生输入和正式 `meme50-v2` 结果用分开的清单与计分适配器。当前管线把图转成可见事实和关键词再调用 DeepSeek 网页搜索，已关闭反向图片搜索入口。[离线工具](yuanjian-benchmark-guide.md) · [正式供应商流程](hkust-deepseek-execution.md)

网页先导题可用以下命令从冻结清单中生成。程序选择三个不同开发家族的授权样本，匿名题目仅带截图，另存原件与来源答案。前两行均为本机操作。后两行分别用于运行已配置的联网服务和复核下载后的原件，联网前核对供应商、预算及评测环境。

```powershell
& $py -m scripts.retrieval_web_batch freeze .cache/meme-eval-cn/manifest.json .cache/meme-web-pilot --limit 3
& $py -m scripts.retrieval_web_batch score .cache/meme-web-pilot --out .cache/meme-web-pilot/preflight.json
& $py -m scripts.meme50_acceptance run-suite --manifest .cache/meme-web-pilot/manifest.json --split development --base-url http://127.0.0.1:8000 --out .cache/meme-web-run --target-count 50
& $py -m scripts.retrieval_web_batch score .cache/meme-web-pilot --runs .cache/meme-web-run --out .cache/meme-web-score.json
```

17:30（北京时间）检查清单哈希、实际合格样本数、已完成/失败/排队/尚未提交的题数、证据位置和预算用量。留出集尚未执行时填待运行。保留同版全部首轮结果，另记补跑批次。
