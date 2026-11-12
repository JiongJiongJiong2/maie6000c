# meme50-v2 实施与验收记录

2026-11-12 续验收记录见 [本轮完整验收执行报告](meme50-acceptance-20261112.md)。新版本 292 项 Python/PostgreSQL、18 项浏览器回归及适用旧搜索 smoke 已通过；授权和产品质量仍 pending。以下保留上一轮原始记录，不覆盖历史失败。

执行跨 2026-11-11 / 2026-11-12（香港时间）。基线 `c34d9f6`，分支 `codex/real-gif-acquisition`。全程单 agent，保留原有未提交改动，没有推送、合并或清空数据库。

**状态：实现及内部工程检查通过；产品的真实自动联网搜索、40–50 条数量和相关性门槛未通过验收。** 缺少 Gemini / Google Vision / Brave 凭据，不将受控响应、旧九候选或本地库命中作为外部能力证据。

小型脱敏汇总见 [机器及真实运行摘要](evidence/meme50-summary.json)。原始截图、输入与完整逐次记录保留在忽略目录。

## 阶段结果

| 阶段 | 本轮实际完成 | 尚未完成 |
| --- | --- | --- |
| M0 | 保存现有基线；只检查凭据存在性；固定 provider 适配和独立计数 | 三类外部服务的实际授权调用，当前密钥均不存在 |
| M1 | 多格式、可选描述、独立 v2 web job、最多 50、真实 PG 迁移及旧外键保留 | 无已知内部契约阻塞 |
| M2 | 真实解码/方向/透明/时间抽帧；云端及证据结构；错误路径；图片不使用文件名语义 | 云端画面分析正确性、不确定身份的真实联网修正 |
| M3 | 两种真实 REST 适配；共享 ledger；隔离出口；未预置公网媒体及通用网页提取真实成功 | 带授权的两种召回通道联跑、表情来源覆盖及服务使用约定验收 |
| M4 | 受控编排可流式发布 50 个混合格式不同组；时间轴/尺寸去重及稳定排序 | 三个预筛资源充足案例、真实数量/相关性、评分校准、p50/p95 |
| M5 | 正式页直接 v2；实际 PG+API+独立 worker 空文字 GIF 上传、明确失败、刷新和新 attempt 重试；非 root 容器 CLIP 图像/文本推理 | 实际外部搜索成功、真实 50 项分页及动静态下载 SHA/播放闭环 |
| M6 | 冻结 3 份开发与 12 份独立输入、原始 SHA、规则、空文字和动画分布 | 留出运行、A/B 核验收益、人类相关性标注和另一位成员复现 |

## 机器检查

完整 PostgreSQL 回归记录 `.cache/meme50/python-postgres-delivery.txt`，最终 **279 passed、2 deselected（既有 smoke）**，PostgreSQL 测试实际执行，没有按 SQLite 替代或跳过。包含旧数据 downgrade/upgrade、复合 review 外键保留、新 50 条静态持久化、不兼容数据降级拒绝、并发幂等、legacy 三 GIF 回归、新格式/分页/草稿协议/硬超时进程组测试。

网页回归 `.cache/meme50/web-delivery-tests.txt`：**17 passed**，覆盖 client/design 旧流程和新 meme50 页的空描述、分页 20/20/10、静态筛选、下载与刷新恢复。其响应明确受控，**不是 M5 公网成功证据**。发现并修复新 profile 恢复时误用旧三候选验证器的问题。最终纯文案格式化不改变行为。

`ruff check .`、`git diff --check`、`npm --prefix web run format:check` 通过。真实进程测试调用系统 `ps`；本机受限沙箱禁止时，通过工具审批执行完整测试，不把权限错误改成假通过。普通回归未调用付费外部服务。

多格式测试覆盖静态 PNG/JPEG/WebP/GIF、动画 GIF/WebP/PNG、WebP 解码后读取真实时长、空白首帧、EXIF、透明白底、损坏及字节限额、路径逃逸；去重保留时间轴中的重复帧位置，不仅比较去重后的单帧集合。API 验证每项原始 SHA、实际 MIME、格式和帧数；静态不伪装 GIF。

## 真实运行证据

`.cache/meme50/public-egress.json` 记录隔离服务的实际结果（只验证获取，不评价相关性）：

| 操作 | 结果 |
| --- | --- |
| 未预置的 `www.python.org` PNG | HTTP 200，实际 peer `151.101.0.223`，PNG 211×71，SHA `ea0e73137c1c8561e91241771e3c81e5b3e8f5ab2cbfdad1a00d8eea524815fa` |
| 通用 `www.mozilla.org/en-US/` 页面 | HTTP 200，实际 peer `151.101.131.19`，解析四个实际图片线索 |
| 上页 og:image | HTTP 200，PNG 1200×630，SHA `594c404fb43669caf9833a3d6821d367e8f3e448742ef1e3e9c1356abcafd27c` |
| `169.254.169.254` 元数据地址 | HTTP 422 `url_policy`；DNS=0、TCP=0、HTTP GET=0 |

使用明确 DoH 配置避开本机 fake-IP DNS；连接固定公网数字地址，TLS 仍验证原 host。受控测试另验证混合私网 DNS、实际 peer 不匹配、重定向至元数据地址均拒绝。以上没有把 Python 标志或 Mozilla 宣传图作为相关表情候选。

`.cache/meme50/browser-live.json` 与 `live-empty-text-failure.png` 是无 route interception 的正式浏览器运行：

- request `ebe42dc3-9f32-40f8-814b-3b91dfcff261`
- 初次 job `f30b0e9c-8752-4c7f-89d7-f6d0a4405625`
- retry job `be70d59e-f7d6-41da-a4aa-376c0aef21a3`
- 空文字，上传原 GIF；页面无 JS 错误；刷新恢复；失败后新 attempt。
- 实际失败 `visual_provider_unconfigured`，候选数 0，没有 final revision、真实查询或媒体下载。这是可定位失败的证据，不能声称识图成功。

最终交付脚本再次运行：request `d52a719a-2256-4302-a07d-9154d7532d4b`，job `1f2c6cd7-5c8e-4386-99ad-038a779c44b1`，retry `2f07dba6-c0ac-493d-acf7-1c0d9aff88f5`；`.cache/meme50/browser/final-attempt/` 保存截图及无拦截记录，刷新恢复且无 JS 错误。

真实 API 验证脚本结果 `.cache/meme50/runs/dev01/evidence.json` 记录独立上传、幂等重放、阶段和相同实际失败，exit 2。最终又分别运行 PNG、JPEG、WebP 和另外两份 GIF，`.cache/meme50/runs/dev-format-*`、`dev-02-gif`、`dev-03-gif` 保留每次独立空文字任务，均在同一明确配置错误处失败、结果为零。后续运行目录保留每次独立结果，不合并候选凑数量。

worker 镜像实际构建；`.cache/meme50/worker-model-runtime.json` 记录网络关闭、模型只读挂载、UID 10001，图像与文本编码均 `[1,512]`。这是本地排序模型可运行的证据，与云端识图、网页核验和直接以图搜图分开。模型缺失时不生成伪向量。

## 冻结样本与质量审阅

[冻结清单](meme50-evaluation.json) 包含实际文件 SHA、来源及格式。开发集为用户三份 GIF，已调试，不能算留出；它们的来源充足性尚未预筛。留出为新下载的 8 张 Twemoji 静态输入和 4 份 Noto 动画，随机本地文件名，与三份开发 GIF 家族分离。8 条空文字，4 条使用预定的一般动作/情绪偏好。原图在忽略的 `.cache/meme50/inputs/`，不把来源编码或文件名交给识别模型。全部 12 份已解码与 SHA 冻结；它们以 emoji 为主，不能外推至所有真实梗图分布。

留出没有运行模型或检索，没有用结果调整阈值。冻结清单的实现摘要用于后续复现；如配置改变，先提升版本并重新冻结，不能把旧留出当作未见集继续调参。已知原有 12 张本地演示库没有冒充新增留出。

标注区分“明确相关、部分相关、无关”；precision 只计明确相关，并保留分母、低数量和失败案例。Top10 宏平均 ≥90%、实际 Top50 宏平均 ≥80%、内容重复零、资源充足三例各 40–50、首批预览 30 秒/最终 180 秒仍是**待测门槛**，没有已达标数值。核验纠正/误导的 A/B 对照尚未运行。真人标注和独立成员复现均 pending，不把 AI 复核当作真人意见。

## 交接

运行方法及数据外发边界见 [meme50 说明](meme50.md)。新增真实工具：

```bash
.venv/bin/python -m scripts.verify_meme50 --image INPUT \
  --target-count 50 --out .cache/meme50/runs/UNIQUE-ATTEMPT
node scripts/verify_meme50_browser.mjs --image INPUT \
  --out .cache/meme50/browser/UNIQUE-ATTEMPT
```

最小外部缺项是已授权、可用的视觉模型、Google Vision 及 Brave 搜索凭据；随后逐份运行冻结清单，完成真实数量/媒体/SHA/网页闭环，再由真人标注和成员复现。未开新付费账号、未读取其他项目秘密、未输出凭据。当前实现可以审阅，但不能宣布完整产品验收完成。
