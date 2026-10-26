# W07 团队任务与开发约定

本周先完成 MemeRetrieve 的网页演示版本：用户上传一张已裁剪的截图，在小型 GIF 库中进行真实模型检索，预览候选并确认、下载。先用 10–20 个有使用权限的 GIF 打通链路，再按进度扩充。原生 iOS 客户端、互联网搜索、微信导出和自动裁剪安排到后续阶段。W07 提交时说明相对 W04 的范围调整和实际完成数量。

这里约定的是本周实现目标；已实现、部分实现和未实现的状态，在最终的 `submissions/week07/README.md` 中如实记录。

**整体链路按下面的顺序实现。**

```text
网页上传截图
  → API 保存图片，并把请求和待处理任务写入 PostgreSQL
  → API 返回 request_id、job_id；网页开始查询状态
  → 独立 worker 领取任务，调用真实模型检索 GIF 库
  → worker 把候选和最终状态写回 PostgreSQL
  → 网页显示最多三个 GIF，用户确认或全部拒绝
  → API 保存用户决定；用户下载 GIF 并检查动画播放
```

API 在图片可读取、请求和任务已提交到数据库后才返回接受成功，检索在 worker 中完成。worker 直接调用检索模块，沿用 W04 提案的模块边界；Haoxuan 同步调整启动配置。任务结果、人工选择、文件下载分别记录或展示，不能把它们当成同一个“成功”。日志带上相应的 request_id 和 job_id，演示时可以核对。

**四人按以下交付物分工。**

| 成员 | 本周负责 | 交付和验收 |
|---|---|---|
| Jiongle He | 范围、验收、文档和提交 | 明确演示用例；汇总实际测试证据与风险；维护架构、运行说明和 W07 README；组织演练、核对 tag 和 Canvas 提交 |
| Haoxuan Jiang | 后端、数据库、worker 和部署 | 请求、任务、候选、审阅记录及迁移；上传、状态、媒体、审阅接口；worker 调度；Docker 启动与持久化验证 |
| YuanJian Li | GIF 库、模型和检索 | 素材清单及使用依据；抽帧、特征准备和真实查询推理；可被 worker 调用的检索模块；结果与失败示例 |
| Zirui Huang | 网页和端到端联调 | 上传、状态查询、GIF 预览、确认/拒绝和下载；接入真实接口并主导整条链路联调 |

每个人交付可运行代码、运行方法和实际验证结果。Haoxuan、YuanJian、Zirui 分别说明自己模块的配置与限制，Jiongle 汇总进文档。单独运行成功后，要继续参与端到端联调。

**前后端先统一下面几个接口。**

| 接口 | 最小约定 |
|---|---|
| `POST /search-requests` | multipart 字段为 `image`、`client_submission_key`；接受成功返回 `202`，包含 `request_id`、`job_id`、`status` |
| `GET /search-requests/{request_id}` | 返回 `request_id`、`job_id`、`status`、`result_kind`、`candidates`、`error` |
| `GET /candidates/{candidate_id}/media` | 返回真实 GIF 文件，供预览和下载 |
| `POST /search-jobs/{job_id}/reviews` | JSON 字段为 `decision`、`candidate_id`、`client_review_key`；保存后返回 `review_id` |
| `GET /health/live`、`GET /health/ready` | 分别检查 API 存活和依赖是否可用；worker 进展通过任务记录和日志核对 |

JSON 使用 snake_case，ID 统一为 UUID 字符串。候选字段固定为 `candidate_id`、`rank`、`score`、`media_url`，网页使用 media_url，不接收服务器本地路径。状态只用 `pending → running → completed / failed`；completed 的 result_kind 为 `candidates` 或 `no_candidates`。未完成时 result_kind 为 null；正常情况下 error 为 null，失败时为包含 `code`、`message` 的对象。没有候选和程序执行失败分开显示，score 作为相似度排序信号展示。

网页因网络问题重发同一次上传时，复用 client_submission_key；后端返回原 request/job，相同 key 配不同图片返回冲突。换图或用户重新发起搜索才生成新 key。decision 只用 `accept` 和 `reject_all`：accept 必须带属于该 job 的 candidate_id，reject_all 的 candidate_id 为 null。审阅重发复用 client_review_key，后端避免重复写入，相同 key 配不同内容返回冲突。Zirui 和 Haoxuan 在联调前各确认一份实际请求和响应示例；字段变化先同步，再一起修改调用端。

**worker 与检索模块保持一个简单边界。**

检索代码放在 `services/retrieval/`，由 YuanJian 提供 `search(image_path, top_k=3)`。返回值包含 `matches`、`model_version`、`corpus_version`；matches 按分数降序排列，每项有 `reference_asset_id` 和 `score`。GIF 清单使用固定的 reference_asset_id，由 YuanJian 提供、Haoxuan 导入数据库，检索结果与素材记录使用同一 ID。

检索模块只负责读取图片、推理和排名；Haoxuan 的 worker 负责领取任务、写入候选和更新状态。模型不可用或读取失败时抛出明确错误，由 worker 记录 failed。GIF 库、输入文件和模型缓存位置通过配置传入，避免写死个人电脑路径；API 和 worker 使用一致的文件目录。YuanJian 先交付一张真实截图到实际 GIF 候选的可运行示例，Haoxuan 据此接入 worker。

**开发中只保留几条协作规则。**

统一使用 [团队仓库](https://github.com/JiongJiongJiong2/maie6000c)。开发流程统一为 **功能/修复/文档分支 → dev → main**。所有工作分支从最新 dev 创建，PR 的 base 选择 dev；main 只接收 dev 中已经验收的内容。dev 用于日常集成并保持可启动，main 保留稳定、可演示的版本。

建议分别使用 `feature/w07-backend`、`feature/w07-retrieval`、`feature/w07-web` 和 `docs/w07-submission`。PR 写清改了什么、怎么运行、如何验证，请另一位组员看过后合并。分小块尽早合并到 dev，避免直接向 dev 或 main 推送日常开发提交。

首次获取仓库并开始自己的任务：

```bash
git clone https://github.com/JiongJiongJiong2/maie6000c.git
cd maie6000c
git switch dev
git pull --ff-only origin dev
git switch -c feature/w07-backend  # 换成自己负责的分支名
git push -u origin feature/w07-backend
```

已有本地仓库时先保存自己的工作，再切换并更新 dev、创建工作分支。提交 PR 前合并最新的 origin/dev 并解决冲突，再运行相关验证；PR 的目标分支仍选择 dev。CI 对 dev/main 的推送以及目标为 dev/main 的 PR 触发检查。

Haoxuan 统筹 `services/common/`、数据库迁移、`compose.yaml`、`.env.example` 和公共依赖变更；其他成员需要改这些位置时先同步。Zirui 负责 `web/`，网页由同一个 API 地址提供并使用相对路径调用接口；YuanJian 负责 `services/retrieval/` 及素材准备说明。个人环境文件、模型权重、批量 GIF 和缓存不提交 Git，提交素材清单、必要版本信息和准备方法。

每天至少做一次最新 dev 代码的联调，说明当天完成、还缺什么、需要谁配合。临时示例数据可以辅助页面开发，最终验收必须接真实 API、真实模型和真实 GIF。遇到接口或依赖阻塞当天说明，由相关两人直接对齐。

**本周按下面的节点推进。**

| 时间 | 必须达到的结果 |
|---|---|
| 今天 | starter 能启动；确认上述接口；完成真实模型与至少一个 GIF 的检索可行性检查；网页上传骨架可运行 |
| 周三 | 上传 → 数据库 → worker → 真实检索 → 结果 → 网页，第一次完整接通 |
| 周四 | 补确认、下载及失败展示；验证重复提交、坏图片、模型不可用、重启后结果保留和 GIF 多帧播放 |
| 周五 | 停止加功能；按运行说明在干净环境复现；演练并更新真实文档、范围和后半学期计划 |
| 周六 | 提前在 dev 验收并预留至少两小时缓冲；通过 dev → main 的 PR 合入稳定版本，从 main 推 `w07-midterm`，核对其 commit SHA，最后提交 Canvas |

演示必须现场展示输入、持久化状态、异步处理、持久化结果和至少一种运行信号。仓库维护 `README.md`、`docs/architecture.md`、`docs/operations.md` 和 `submissions/week07/README.md`；W07 文档写明实际 AI 工具用途及团队验证、修改或拒绝的内容。网页下载不代表已完成 iPhone 本地收藏；截图和录屏可作辅助，现场运行以真实链路为准。截止时间按 Canvas 显示的时区核对。
