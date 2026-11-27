# YuanJian 检索模块交接（2026-11-15）

职责来源：final-project-plan.md，组长提交 73bf03b。本次交付分支为 `codex/yuanjian-retrieval-validation`，基于 Zirui 的 `codex/share-gif` 提交 `6bee092`。检索交付与手机/Windows 网页兼容修复分开提交，便于评审。没有合并到 dev；导入实验、微信分享排查、本机配置和模型不属于此次交付。

本分支继承的多帧检索、收藏复用、继续联网与 GIF 分享由组员先前实现，不能计为 YuanJian 本次新增功能。本次贡献是以下评估工具、索引发布可靠性修复及其测试。兼容修复另见 `yuanjian-web-compatibility.md`。

## 已检查并复用

- origin/feature/w07-retrieval：W07 CLIP 编码基础，db037de。
- origin/dev：1e8feb0，已整合真实媒体获取；不应重新覆盖已有下载、去重、重排代码。
- origin/codex/real-gif-acquisition：来源与动画获取证据、gif-user-sample-test.md；三份 GIF 输入的检查不是独立截图盲测。
- origin/codex/saved-gif-reuse：424c5fb，收藏后的 saved_index 模块与就绪索引检索；当前 checkout 已包含。
- origin/codex/continue-web-search 与 origin/codex/share-gif：原截图续搜与网页分享；当前基础为 6bee092。
- origin/feature/backend-final-integration：c34d9f6，后端独立集成改动；没有直接合并，避免用较旧分支覆盖新媒体/收藏实现。

保持 prepare_candidates(image_path, sources, work_dir, budget)、search(image_path, top_k=3)、index_saved_asset(asset_id) 的签名和返回约定。沿用现有模型版本、8 帧抽样、索引格式和 0.82 阈值；未修改 API、共享模型、agent 编排、数据库或 worker。

## 本次新增和修改

1. services/retrieval/evaluate_local.py：离线运行真实 CLIP，在现有演示库上比较首帧索引与多帧索引。校验库文件 SHA 与索引模型/manifest 版本，输出逐样本目标、原文件 SHA、帧数、排名、耗时及命中分母。使用每个 GIF 的三分之一帧作为查询；不接触最终验收集、不调用外部搜索、不改现有索引。结果明确标记 derived_frame_demo_ablation_not_held_out。
2. services/retrieval/engine.py：建索引复用已有 atomic_write，以唯一临时文件完成发布，避免原来所有重建共用 gif-frames.tmp。索引路径和 NPZ 字段不变；增加内存缓冲，适用于本计划小库，大库需另评估峰值内存。并发发布最终仍是最后完成者胜出，manifest 版本检查继续拒绝陈旧索引。
3. tests/unit/test_retrieval_publication.py：实际创建并读取索引，注入发布失败后确认旧索引字节未变。没有声称完成多进程并发压力测试。
4. services/retrieval/benchmark.py、tests/unit/test_retrieval_benchmark.py：离线校验正式样本及汇总已提供的 A/B/C 结果，检查哈希、动画、重复、划分泄漏和预算，保留失败分母及缺失实验项。工具不发起联网搜索，不代表正式 A/B/C 已执行。输入示例和运行命令见 `yuanjian-benchmark-guide.md`。

## 运行命令

在仓库根目录 PowerShell 中，使用既有环境，无需重新安装：

```powershell
$py = 'C:\Users\L\.conda\envs\maie6000c-retrieval\python.exe'
& $py -m services.retrieval.evaluate_local --output .cache/yuanjian-local-evaluation.json
& $py -m pytest -q tests/unit/test_retrieval_publication.py --basetemp=.cache/pub-test
& $py -m pytest -q tests/unit/test_retrieval_benchmark.py --basetemp=.cache/bench-tests
& $py -m pytest -q tests/unit/test_retrieval.py tests/unit/test_candidate_preparation.py tests/unit/test_encoder.py tests/unit/test_meme50_media.py --basetemp "$env:TEMP\yj-retrieval-check" --tb=short
& $py -m ruff check services/retrieval/evaluate_local.py services/retrieval/engine.py tests/unit/test_retrieval_publication.py
git diff --check
```

前置条件：data/reference/manifest.json 及原 GIF、data/models 下现有 CLIP 权重和 gif-frames.npz。缺少或陈旧索引时先运行 `python -m services.retrieval.engine index`。评估不启动公网入口、不需要数据库。上述 python 应使用指定 $py。

## 本轮实测结果

发布前定向复测：评估/索引发布单元测试 11 项、网页资源集成测试 3 项，共 14 passed；本次涉及的 Python 文件 Ruff 通过。网页集成测试使用隔离 SQLite 测试库，不是完整 PostgreSQL 回归。

- 真实模型、12 个本地演示 GIF：首帧 Top-3 11/12，多帧 Top-3 12/12。逐项证据：yuanjian-local-evaluation-20261115.json。计时包含第一次冷模型加载，不能直接当线上延迟分布。
- 新增索引发布回归：1 passed。
- 既有四组回归：64 passed、2 failed。两项失败都是 Windows 未授予符号链接创建权限（WinError 1314），无法完成对应安全断言；没有跳过后冒称全绿。
- Ruff 和 git diff --check 通过。
- 初次在较长工作区临时路径下，收藏索引创建失败；换较短系统临时目录后同一收藏索引测试通过。这说明 Windows 长路径兼容是独立部署风险。共享 atomic_write 和存储路径属于 Haoxuan；如要改短临时文件名或部署根目录，需与其协调，不能擅自改变资产/索引路径契约。本次没有改系统长路径或开发者模式设置。

## 验收范围及尚未验证的部分

用户本次选定本机已有 12 个演示 GIF 验证本地功能。下述正式样本和 A/B/C 是组长计划里尚未完成的项目级工作，不是此次交付已经达到的结果；演示 GIF 评估不替代真实截图盲测。

仓库 gif-acceptance-cases.json 的 eligible_case_count 为 0，输入路径和真人确认尚空；旧来源证据不能当作本轮真实联网复测。组长需提供真实截图需求及目标证据、开发集家族划分和相同来源/预算的 B/C 配置，Zirui 保管最终验收集。本次首帧/多帧对照不替代计划中的 A 本地、B 直接描述联网、C 规划补搜三组对照。

正式 A/B/C、开发集一轮改进、冻结后最终验收、至少 30 个真实需求样本、独立真人判分均尚未完成。不得用 12/12 宣称真实截图找回率 100%。本次没有重跑联网来源、PostgreSQL 重启恢复或真机分享；前次手机分享记录保存在工作区验证说明.md。建议交接先检查短路径部署和符号链接安全测试，再收齐样本执行正式评估。
