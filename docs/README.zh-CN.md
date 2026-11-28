# MemeRetrieve 文档总目录

[English](README.md) · 简体中文 · [仓库首页](../README.zh-CN.md)

| 从这里开始 | 你可以找到 |
| --- | --- |
| [产品说明](product/README.zh-CN.md) | 使用场景、功能边界、实测结果和商业试点设想 |
| [使用与部署指南](guides/README.zh-CN.md) | 注册与搜索、私人收藏、Docker 部署、邀请制演练、升级和回滚 |
| [技术文档](technical/README.zh-CN.md) | 系统架构、API、worker、pgvector、NPZ 回退、迁移与测试 |

## 当前交付与验收证据

[W13 交付报告](../submissions/week13/README.md) · [技术复盘](../submissions/week13/final-technical-brief.md) · [AI 使用说明](../submissions/week13/ai-use-statement.md)

| 要查证的问题 | 运行记录 |
| --- | --- |
| 从正式网页联网找回原件后，重启离线还能否找回？ | [浏览器验收](../submissions/week13/browser-release-verification.json) |
| 旧收藏能否迁移，pgvector 与 NPZ 路径能否返回同一资产？ | [向量数据库验收](../submissions/week13/pgvector-verification.json) |
| 单帧与多帧索引在 12 份参考素材上的表现如何？ | [逐例评测](../submissions/week13/local-corpus-evaluation.json) |
| 邀请注册、离线检索与原件下载是否在本机公测环境通过？ | [重启前后回执](../submissions/week13/public-beta-rehearsal.json) |

## 专题与历史原件

以下为按主题整理的原始材料。链接后的标记是原文语言或数据格式。带日期的记录反映对应版本的运行状态；操作当前版本请使用上方的指南。

<details>
<summary>网页、API 与存储</summary>

| 原件 | 语言 / 格式 |
| --- | --- |
| [项目架构与原始设计](architecture.md) | EN |
| [后端接口与媒体生命周期](backend-guide.md) | EN |
| [后端开发日志](backend-development-log.md) | 中文 |
| [服务运维记录](operations.md) | EN |
| [原生启动器与本地演示](local-demo.md) | EN |
| [架构图](figures/README.md) | EN |
| [W07 网页端集成](../web/README.md) | EN |
| [网页设计说明](../web/DESIGN.md) | EN |
| [浏览器兼容核查](yuanjian-web-compatibility.md) | 中文 |
| [私人库功能验收](private-meme-library-p0-p1.md) | 中文 |
| [私人库交付记录](private-meme-library-acceptance.md) | 中文 |
| [大 GIF 还原验收](private-library-large-restore.md) | 中文 |

</details>

<details>
<summary>检索、来源与供应商</summary>

| 原件 | 语言 / 格式 |
| --- | --- |
| [搜索 Agent 开发交接](web-search-agent.md) | 中文 |
| [图片优先检索模式](meme50.md) | 中文 |
| [HKUST、HKGAI 与 DeepSeek 接入](hkust-deepseek-execution.md) | 中文 |
| [HKUST 配置记录](hkust-meme50-setup.md) | 中文 |
| [供应商授权记录](meme50-authorization.md) | 中文 |
| [GIF 来源支持情况](gif-source-support.md) | EN |
| [原件获取与交接](gif-acquisition-verification.md) | EN |
| [独立搜索 Agent 实验](meme-agent-v1.md) | 中文 |
| [试验工作区](../experiments/meme_search/README.md) | 中文 |
| [试验方法](../experiments/meme_search/protocol.md) | EN |
| [试验接口约定](../experiments/meme_search/mvp_contract.md) | EN |
| [试验 Agent 操作步骤](../experiments/meme_search/meme-search-skill.md) | EN |

</details>

<details>
<summary>检索评估与历次运行</summary>

| 原件 | 语言 / 格式 |
| --- | --- |
| [评估方法与数据划分](yuanjian-benchmark-guide.md) | 中文 |
| [三份用户 GIF 与九个候选](gif-user-sample-test.md) | EN |
| [联网检索验证记录](meme50-verification.md) | 中文 |
| [真人评审说明](meme50-human-review.md) | 中文 |
| [11 月 12 日验收记录](meme50-acceptance-20261112.md) | 中文 |
| [真实服务运行记录](meme50-live-20261112.md) | 中文 |
| [v8 冻结评测结果](meme50-v8-results.md) | 中文 |
| [去重修复与验收](meme50-dedup-fix-20261113.md) | 中文 |
| [早期目标审计](meme50-goal-audit.md) | 中文 |
| [检索模块交接](yuanjian-handoff-20261115.md) | 中文 |
| [各分支评估材料核查](yuanjian-branch-material-audit.md) | 中文 |
| [可机读运行与失败记录](evidence/) | JSON |

</details>

<details>
<summary>分享和导入实验</summary>

| 原件 | 语言 / 格式 |
| --- | --- |
| [WhatsApp 网页导入实验](whatsapp-web-import-experiment.md) | 中文 |
| [实现与复现入口](../experiments/whatsapp_web_import/README.md) | 中文 |
| [微信分享核查](wechat-gif-sharing-investigation.md) | 中文 |
| [QQ 导入可行性](qq-import-feasibility.md) | 中文 |

</details>

<details>
<summary>课程材料与仓库维护</summary>

| 原件 | 语言 / 格式 |
| --- | --- |
| [W03 个人准备实验](../submissions/week03/README.md) | EN |
| [W04 团队方案](../submissions/week04/README.md) | EN |
| [W07 期中演示](../submissions/week07/README.md) | EN |
| [W07 集成计划](week07-plan.md) | 中文 |
| [团队分工与评估设计](final-project-plan.md) | 中文 |
| [期末收尾计划](final-closeout-plan.md) | 中文 |
| [课程模板使用指南](starter-guide.md) | EN |
| [课程模板架构](starter-architecture.md) | EN |
| [基础技术选型](adrs/0001-baseline-stack.md) | EN |
| [课程提交与 AI 声明模板](../templates/) | EN |
| [GitHub 仓库管理工具](../tooling/github/README.md) | EN |
| [CI 工作流与问题模板](../.github/) | EN |

</details>
