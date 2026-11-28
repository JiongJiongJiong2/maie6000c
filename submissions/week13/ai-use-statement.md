# AI 使用与验证

本项目运行时可以使用 HKUST 或 HKGAI 理解上传截图的可见内容，DeepSeek 负责查询规划和网页搜索，本地 CLIP 计算图像与文字表示。模型输出提供检索线索。原件身份以实际文件、解码帧数、来源和 SHA-256 核对，收藏决定由用户在网页上作出。

本次交付使用 Codex 和 GitHub Copilot（Copilot SDK in VS Code）辅助代码检查、分支整合、Windows 路径与时区修复、测试和交付文档整理。Copilot 还协助对照最终项目要求检查文档、整合最新评测信息并完善双语产品定位。团队需审核 AI 建议；文档将当前截图检索、人工审核和用户主动分享与尚未实现的文化本地化、自动跨平台发布明确区分，没有把机器评测表述为真实用户成绩。

验证包括真实供应商调用、浏览器下载比对、隔离 PostgreSQL 的迁移和状态核对，以及已授权参考库的单帧和多帧对照。线上未命中的运行也计入工程记录。中文 meme 家族留出评测中的机器结果、失败类别及待完成人工盲评均在交付材料中注明。

团队成员的独立复现与课程要求的个人声明须由对应成员本人填写。当前证据包含自动化与真实服务的工程操作记录；独立用户需求及真人判分尚未形成可报告的样本集。

---

# English translation

At runtime, the project may use HKUST or HKGAI to interpret visible screenshot
content, DeepSeek for query planning and web search, and local CLIP for image
and text representations. Model output provides retrieval signals. The
original asset is checked against its file bytes, decoded frame count, source,
and SHA-256; the user makes the save decision in the web application.

Codex and GitHub Copilot (Copilot SDK in VS Code) assisted with code review,
branch integration, Windows path and time-zone fixes, test writing, browser
operation, and delivery documentation. For final packaging, Copilot also
helped check the course requirements, incorporate the latest evaluation
record, and refine the bilingual product positioning. The team must review AI
suggestions. The documentation distinguishes current screenshot retrieval,
human review, and user-directed sharing from cultural localization and
automated cross-platform publishing, which are not implemented; machine
benchmark results are not presented as real-user outcomes.

Verification included live provider calls, browser downloads compared with
retained originals, migrations and state checks in an isolated PostgreSQL
deployment, and single-frame versus multi-frame comparisons on permitted
reference media. Unsuccessful online runs were retained in the engineering
record. The Chinese-meme family-held-out results, failure categories, and
pending human blind review are explicitly documented.

Each team member must complete their own reproduction sign-off and any
individual declaration required by the course. Current evidence includes
automated tests and recorded engineering runs; an independent user-request
dataset and human relevance scoring are not yet available as a reportable
sample.
