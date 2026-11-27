# 远端分支评估材料核查（2026-11-15）

本记录描述 2026-11-15 的材料核查：当时已 git fetch 刷新全部 origin 分支，扫描全部15个远端分支的 docs、experiments、submissions 中的 Markdown/JSON/CSV/JSONL/YAML，按 Git blob 去重后检索并阅读相关证据。完整匹配清单见本机 .cache/branch-evaluation-audit.json（本机诊断产物，不随 Git 交付）。核查操作没有修改远端；本报告随 YuanJian 交付分支保存。它不代表未来新增分支或材料的状态。

## 修正之前的判断

不能说仓库没有划分或验收安排：Zirui 的 real-gif-acquisition 分支已有 meme50 评估材料，也已随集成进入 dev、saved-gif-reuse、continue-web-search、share-gif。它们不直接满足 final-project-plan.md 的原 GIF 找回 A/B/C 标准。

| 材料 | 已有内容 | 仍缺或不匹配 |
| --- | --- | --- |
| experiments/meme_search/protocol.md、queries.json、reviewed_judgments.json | 8个人工构造描述、literal/rewrite/skill三组固定查询、同一host搜索工具、AI审阅 | 文档明确是文字到网页的pilot，非真实截图或真人标注；不是A本地/B直接联网/C规划补搜 |
| docs/gif-acceptance-cases.json | 原GIF来源提议、目标SHA、帧数 | eligible_case_count=0；真实截图和真人目标确认未填写 |
| docs/gif-user-sample-test.md | 用户提供的3个GIF及候选检查、字节命中情况 | 输入是GIF抽帧、跨多次尝试，不是独立盲测；本地缓存文件未随Git交付 |
| docs/meme50-evaluation-v8.json、v9.json | 15例：3 development、12 heldout；输入SHA、family、来源、冻结配置/指纹 | 主要评估约50个相关动静态素材；并非每例都有唯一原GIF目标；本机15个input_path均不存在 |
| docs/meme50-human-review.md | 开发/留出审阅页、标签导出、score命令、真人独立复现要求 | 是操作安排，不是签署结果；标签和独立复现仍pending |
| docs/meme50-v8-results.md | 记录15例共575个实际解码文件、运行耗时/调用数、复现包位置 | 这是他人历史执行记录，未在本机复测；真人相关性/去重审阅仍pending |

## 已有配置能否当作统一B/C配置

meme50 的配置很具体：HKUST视觉、DeepSeek Flash规划/官方网页搜索，目标50条，180秒总预算、最多16次搜索等。v8另做身份核验关闭/开启对照，但不是final-project-plan中的B/C。

原GIF两轮agent已有 SearchBudget：最多2轮、6次下载、3候选，默认60秒、每次12秒；QueryPlanner禁用模型时已有固定第二轮描述后缀。这是可复用实现默认值，未找到负责人签署的正式B/C同源配置、初始库/缓存冻结及对应成套结果。不能把两套预算混合后声称公平对照。

## 最小交接请求

不必要求组员从零重做已有安排。请Zirui提供已有 `meme50-v8-reproduction.zip`（文档记录约11.7MB）或其中固定输入及审阅材料，不要提供含密钥的.env；同时说明目前可用于开发的样本，最终保管集不要提前用于调参。需要本人填写的标签/签署不能由agent代填。

请组长确认正式评估继续采用原GIF Top-3 A/B/C，还是采用后续meme50相关性目标。此为评价目标和预算的实质差异，须先协调，不能由检索负责人擅自替换公共验收约定。如果仍采用原GIF协议，已有15例只可作为候选素材来源，必须补原GIF目标证据、真人确认及家族隔离检查；旧heldout已运行及公开结果，不能自动当作新的未见最终集。

结论：已有样本清单、详细运行配置和验收安排可参考；尚未在远端找到可直接完成原GIF正式A/B/C的全部文件与标注。本机仍不能凭Git记录复现缺失的原始素材或完成真人验收。
