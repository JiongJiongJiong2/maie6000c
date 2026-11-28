# MemeRetrieve | 连接中文互联网 Meme 与全球社交表达

> **项目状态（2026-11-28） / Project status (2026-11-28):**
>
> 产品愿景是帮助中文互联网 meme 进入全球社交语境；当前可验证产品能力仍以 GIF 发现、检索、人工确认、收藏和用户主动分享为主。单次工程验收不等于大规模检索效果评估；能力边界与未完成事项见 [W13 交付与证据](submissions/week13/README.md)。
>
> The product vision is to connect Chinese internet memes with global social conversations. The verified product currently focuses on GIF discovery, retrieval, human review, saving, and user-directed sharing. A successful engineering run is not a large-scale retrieval evaluation; see the [W13 delivery report](submissions/week13/README.md) for evidence and limitations.

## 产品定位与当前能力 | Product positioning and current capabilities

**中文**

**产品愿景：**帮助全球用户发现、理解并分享中文互联网 meme，让具有本土文化背景的网络表达更容易进入海外社交语境。

**当前已实现：**MemeRetrieve 可从截图在本地参考库和已收藏素材中查找动态 GIF；未找到时，用户可主动继续联网搜索、检查并播放候选，再确认收藏。收藏的原始文件持久保存并建立多帧索引，之后可离线检索；在设备支持时，用户可通过系统分享面板自行选择分享目标。

**能力边界：**现有参考语料是小规模演示集，并非完整的中文互联网 meme 资源库。产品目前不自动翻译梗的文化语境，也不自动发布到海外社交平台；大规模授权语料、文化解释/本地化及平台发布集成仍需后续设计和验证。

**English**

**Vision:** Help people discover, understand, and share Chinese internet memes, bringing culturally specific expressions into global social conversations.

**Implemented today:** MemeRetrieve searches a local reference corpus and the user's saved library for an animated GIF from a screenshot. If the target is missing, the user can explicitly continue with web search, inspect and play candidates, and confirm a GIF for saving. The original is persisted and indexed across multiple frames for offline reuse. Where supported, the user can choose a destination through the device's share sheet.

**Boundary:** The current reference corpus is a small demo set, not a comprehensive Chinese internet meme library. The product does not yet automatically explain or localize cultural context, or publish to overseas social platforms. A larger rights-cleared corpus, cultural localization, and platform-publishing integrations require future design and validation.

## 系统流程 | System workflow

```text
上传或示例 / Upload or example
  -> 用户裁切确认 / User-reviewed crop
  -> 本地检索 / Local search
  -> 用户主动联网 / User-triggered web search
  -> 下载与动画验证 / Download and animation validation
  -> 人工确认 / Human review
  -> 收藏并索引 / Save and index
  -> 离线复用或用户主动分享 / Offline reuse or user-directed sharing
```

后端由 FastAPI、PostgreSQL 和独立 worker 组成。CLIP 将 GIF 的代表帧编码为向量；产品部署可使用 pgvector 精确检索，并保留经校验的 NPZ 文件作为回退。联网任务使用配置的视觉和网页搜索供应商，外部媒体由隔离的 fetch 服务获取。任务完成、用户接受、原件保存和索引就绪是不同状态。

The backend uses FastAPI, PostgreSQL, and a separate worker. CLIP encodes representative GIF frames as vectors. The product deployment can use exact pgvector search and keeps validated NPZ indexes as a fallback. Online jobs use configured vision and web-search providers; an isolated fetch service retrieves public media. Job completion, user acceptance, original-file persistence, and index readiness are distinct states.

## 已有证据与限制 | Evidence and limitations

**中文**

- 2026 年 11 月 28 日的正式网页验收完成了本地未命中、联网找回、确认收藏、索引就绪、重启并断开外联后的离线再次命中；两次下载与独立留存的原件逐字节相同。详见[验收回执](docs/evidence/gif-acquisition/hkgai-web-offline-20261128.json)。
- 固定的 12 个参考 GIF 小样本中，多帧索引 Top-3 为 12/12，首帧索引为 11/12。该结果只说明这个固定小样本上的表现，不代表真实用户截图的总体命中率。
- 11 月 28 日的中文 meme 机器评测共运行 2,960 次；普通家族留出集 Top-3 首帧为 20/84，多帧为 23/84。输入含程序生成的截图变化，不能视为真实用户命中率；人工盲评和真实需求评测仍待完成。详见[基准报告](docs/retrieval-benchmark-at-scale.md)及[原始证据](docs/evidence/chinese-meme-retrieval-20261128.json)。
- 新增的聊天截图裁切实验中，合成留出集的三类界面截图，整图精确 Top-3 为 2/63，自动像素裁切为 41/63；同时库外返回候选从 0/339 增至 290/339。真实聊天截图和用户误选率尚未评估，结果说明裁切可改善找回但也会增加相似候选，需用户审核。见[裁切评测](docs/chat-screenshot-crop.md)。
- 本地演示首页可选 4 个中文 meme 示例；它们在本地接口与 worker 验收中均以 Top-1 原字节找回（4/4），是固定示例流程检查，不是独立精度评估，单个素材的再发布授权也未全部确认。见[验收记录](docs/evidence/home-example-retrieval-20261128.json)。
- 真实用户需求的大规模 A/B/C 对照、成员独立复现签收及课程平台提交回执仍需团队确认。系统也不承诺从任意网站或截图中必定找回原 GIF。

**English**

- On 28 November 2026, the formal web workflow was verified from a local no-match through online recovery, user confirmation, indexing, and an offline re-match after restart with external access blocked. Both downloads were byte-identical to the independently retained original. See the [acceptance receipt](docs/evidence/gif-acquisition/hkgai-web-offline-20261128.json).
- On the fixed 12-GIF reference sample, multi-frame indexing achieved Top-3 on 12/12 inputs versus 11/12 for first-frame indexing. This result applies only to that small, fixed sample; it is not an estimate of success on arbitrary user screenshots.
- The 28 November Chinese-meme machine evaluation ran 2,960 searches. On the ordinary family-held-out set, Top-3 was 20/84 for first-frame indexing and 23/84 for multi-frame indexing. Inputs included programmatically generated screenshot transformations, so these are not real-user success rates; blind human review and real-request evaluation remain outstanding. See the [benchmark report](docs/retrieval-benchmark-at-scale.md) and [raw evidence](docs/evidence/chinese-meme-retrieval-20261128.json).
- In the new chat-screenshot crop experiment, whole-image exact Top-3 was 2/63 on three synthetic interface categories versus 41/63 with pixel-based auto-cropping; out-of-library queries returning any candidate also rose from 0/339 to 290/339. Real chat screenshots and user misidentification rates have not been evaluated. Cropping can improve retrieval while increasing similar candidates, so user review remains necessary. See the [crop evaluation](docs/chat-screenshot-crop.md).
- The local demo offers four Chinese-meme examples; all four top-ranked downloads matched their original bytes (4/4) in the local API/worker acceptance. This checks a fixed example flow, not independent retrieval accuracy, and not every asset has confirmed republication rights. See the [acceptance record](docs/evidence/home-example-retrieval-20261128.json).
- A larger A/B/C study on real user requests, independent reproductions by all team members, and the course-platform submission receipt still require team confirmation. The system does not guarantee recovery of an original GIF from every website or screenshot.

## 团队分工 | Team responsibilities

| 成员 / Member | 主要负责 / Primary responsibility |
|---|---|
| Jiongle He | Web-search agent, query planning, project coordination and final delivery |
| Haoxuan Jiang | API, database and migrations, background worker, persistence and deployment |
| YuanJian Li | Media validation, visual retrieval, multi-frame indexing and evaluation |
| Zirui Huang | Web client, integration and end-to-end browser verification |

## 文档导航 | Documentation guide

按课程阅读顺序查看[中英文文档索引](docs/README.md)。主要入口：

- [W13 产品交付与证据 / W13 delivery and evidence](submissions/week13/README.md)
- [技术总结与复盘 / Technical brief](submissions/week13/final-technical-brief.md)
- [当前架构与历史设计 / Current and historical architecture](docs/architecture.md)
- [产品运行与 Docker 部署 / Product setup and deployment](docs/product-deployment.md)
- [数据库与向量检索 / Database and vector search](docs/database-and-vector-search.md)
- [后端开发和验证 / Backend development and verification](docs/backend-guide.md)
- [架构决策记录 / Architecture decision records](docs/adrs/README.md)

The [documentation index](docs/README.md) identifies which pages are bilingual, which have a bilingual summary, and which are dated historical records. Historical W04/W07 plans and experiments remain available for traceability and should not be read as the current product status.

## 本地运行 | Run locally

产品安装、参考素材准备、模型下载、供应商配置和 Windows/Docker 启动步骤见[产品部署指南](docs/product-deployment.md)。先运行仅本地检索不需要配置在线供应商；联网搜索需要各部署者自行配置有权使用的凭据。

Follow the [product deployment guide](docs/product-deployment.md) for dependencies, corpus and model preparation, provider configuration, and Windows/Docker startup. Local-only search does not require online-provider credentials; web search requires credentials that the operator is authorized to use.

联网检索只需一把个人 `DEEPSEEK_API_KEY`。在项目虚拟环境运行 `python -m scripts.configure_meme50 --deepseek-only`，按提示隐藏输入密钥。用 `python -m scripts.configure_meme50 --check` 查看配置后重启 API 和 worker。截图理解、OCR、查询规划、网页搜索和可选的私库标注共用这一把密钥。[配置与私库授权](docs/meme50-authorization.md) · [11 月 28 日检索实测](docs/retrieval-progress-20261128.md)

## 历史材料 | Historical material

- [W04 架构提案](submissions/week04/README.md)保留早期目标和方案。
- [W07 交付材料](submissions/week07/README.md)记录中期课程切片及其环境。
- [后半程项目计划](docs/final-project-plan.md)记录分工和评估方案；它是计划文件，不是最新完成状态报告。
- 课程 case/job/triage starter 仍在仓库中，但与 MemeRetrieve 产品流程分开。相关入口见[文档索引](docs/README.md)。
