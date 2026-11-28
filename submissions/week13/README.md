# MemeRetrieve · W13 产品交付

[English](README.en.md) · 简体中文

团队成员为 Jiongle He、Haoxuan Jiang、YuanJian Li、Zirui Huang。产品用一张截图寻找原始动态 GIF，并支持将选中的原件收藏到私人库，下次在本机再次检索。[项目分工](../../docs/final-project-plan.md)

## 运行与演示

在 Python 3.11 环境准备 12 个授权参考 GIF、固定版本的 CLIP 权重和多帧索引，首次启动时执行数据库迁移。Windows 可用本机 PostgreSQL 16 启动器，也可以使用 Docker PostgreSQL 配合主机 worker。[安装与启动](../../docs/local-demo.md) · [数据库与持久卷](../../docs/database-and-vector-search.md)

联网演示需要一个视觉供应商和 DeepSeek。HKUST 为默认选项；使用 HKGAI 时，在项目虚拟环境运行 `python -m scripts.configure_meme50 --provider hkgai --vision-only`。DeepSeek 查询规划和网页搜索共用项目的 DeepSeek 配置。用 `python -m scripts.configure_meme50 --check` 核对当前选择，再启动服务。每位部署者使用自己的授权凭据。[供应商运行说明](../../docs/hkust-deepseek-execution.md)

1. 打开 `/web/`，在启用账户的安装上登录，选择仅本地检索并上传截图。保留本地结果。
2. 当本地结果中缺少目标时，从同一页面点击继续联网搜索，描述画面、动作或记得的出处。网页创建与原始请求关联的新任务。
3. 筛选动画，播放并下载识别出的 GIF。演示前独立保存目标文件的 SHA-256，用它核对下载内容。
4. 点击确认并收藏，等到索引显示就绪。保留数据库、媒体和模型目录，重启 API 与 worker。
5. 在新浏览器会话中登录原账户，禁用对外联网，选择仅本地检索并上传另一帧。检查收藏资产、命中位置和第二次下载的 SHA-256。

## 可复核的证据

随后在已整合分享和兼容改动的发布候选 `48f7693` 上，从空账户再次完成正式网页验收。目标 GIF 联网和重启离线均排第 1，两次下载与独立原件逐字节相同。该次 50 条结果包含 46 张静图和 4 个动画，网页筛选数与数据库一致。联网候选卡和离线收藏卡均成功为系统分享菜单准备原 GIF。[发布版实际任务与下载回执](browser-release-verification.json)

11 月 28 日从正式 Chrome 页面用 HKGAI 和 DeepSeek 找回 Wikimedia Commons 的 44 帧地球 GIF。用户给出了来源站点和画面描述，两个搜索请求分别用了不同抽帧。目标联网第 1，确认收藏后索引就绪，重启服务并禁用外联后本地第 1。网页的两次下载与独立留存的 1,001,718 字节原件逐字节一致。回执保留了成功之前六次尝试中遇到的路径故障与原件未命中。[正式网页回执](../../docs/evidence/gif-acquisition/hkgai-web-offline-20261128.json)

固定参考库的 12 个 GIF 在同一阈值 `0.82`、同一模型、同一组输入下，首帧索引 Top-3 为 11/12，多帧索引 Top-3 为 12/12。输入取自每个源 GIF 约三分之一处的帧。逐项 SHA、帧号、得分与实际耗时在结果文件中。[本次本地运行](local-corpus-evaluation.json) · [评估方法](../../docs/yuanjian-benchmark-guide.md)

[技术总结](final-technical-brief.md)记录工程验证和检索局限。[AI 使用说明](ai-use-statement.md)记录模型职责及验证方式。独立用户截图的真实命中率、其他成员的复现签字，以及课程平台的提交回执由团队另行确认。

## pgvector 与产品部署

已验证原账户库的逻辑恢复、旧收藏回填、固定参考库 96 帧同步，及跨账户隔离。使用正式网页收藏一份 44 帧 GIF，重启和断网后通过 pgvector 在第 1 名找回，下载文件与原件逐字节一致。移除一条旧收藏的派生向量后，NPZ 回退找回同一资产。公共参考库另用 Noto 样例验证第 1 名、原件下载和无候选三种状态。 [迁移、离线与下载回执](pgvector-verification.json) · [产品使用与 Docker 部署](../../docs/product-deployment.md)

## 邀请制公测演练

11 月 28 日在独立的本机部署上完成 Chrome 演练。无效邀请码注册返回 403，有效邀请码注册返回 201，匿名访问私人库返回 401。导入授权的 44 帧 GIF 后，用第 13 帧截图首位命中；重建 API 和 worker、在全新浏览器登录后，第 29 帧仍把同一资产排在第一。前后两次下载均与 1,001,718 字节原件逐字节相同。该部署关闭外部搜索。外部 HTTPS 访问和真实参与者的检索质量仍待验收。[公测演练回执](public-beta-rehearsal.json) · [公测手册](../../docs/public-beta.md)
