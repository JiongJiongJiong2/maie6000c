# meme50 v8 真实验收结果

总体 **pending**，不是完整验收通过。机器阶段已完成；真实相关性、视觉重复标签和另一位成员独立复现尚未发生。没有代填 reviewer、标签或成员身份。

当前分支 `codex/real-gif-acquisition`，保留全部未提交工作、历史数据库和失败。未推送、未合并。供应商仅 HKUST（`gemini-2.5-flash-lite`）及 DeepSeek（`deepseek-flash`、官方网页搜索）。像素反搜明确禁用。配置、代码与本轮证据版本一致，`version_mismatch=false`。

## 门槛

| 项 | 状态 | 证据范围 |
| --- | --- | --- |
| A0 | passed | 学校/DeepSeek 四类实际调用及正式 worker 绑定 |
| A1 | passed | 空文字理解、多角度查询、真实网页核验 |
| A2 | passed | Flash 规划、实际网页召回与媒体获取；像素反搜禁用 |
| A3 | passed | 正式 API/worker/DB、媒体及分页契约 |
| A4 | pending | 三资源各50个机检结果；视觉不同内容和无重复仍需真人 |
| A5 | pending | 12例已运行；Top10、返回列表相关性及视觉重复待真人标签 |
| A6 | passed | 当前版本真实50条正式网页、动静态下载、动画与恢复 |
| A7 | passed | 344项 Python/PG、18项前端及适用部署检查 |
| A8 | pending | 真实另一成员独立复现及人审签署尚未发生 |

## 正式单次任务数量

三资源在预筛40个真实可用内容后冻结，每例单次 target50；12个冻结留出全部运行。所有15例均通过机器及数据库核对，合计 **575 个实际下载并解码的文件**。这不是575个已经由真人确认相关且无重复的内容。

| 案例 | 返回 | 静态 / 动态 | 停止原因 |
| --- | ---: | ---: | --- |
| resource-homer | 50 | 11 / 39 | target_reached |
| resource-pepe | 50 | 9 / 41 | target_reached |
| resource-tom-jerry | 50 | 21 / 29 | target_reached |
| heldout-v2-01 | 24 | 6 / 18 | media_attempts_limit |
| heldout-v2-02 | 50 | 11 / 39 | target_reached |
| heldout-v2-03 | 49 | 16 / 33 | media_attempts_limit |
| heldout-v2-04 | 36 | 12 / 24 | query_limit |
| heldout-v2-05 | 41 | 8 / 33 | query_limit |
| heldout-v2-06 | 50 | 10 / 40 | target_reached |
| heldout-v2-07 | 8 | 4 / 4 | query_limit |
| heldout-v2-08 | 12 | 10 / 2 | media_attempts_limit |
| heldout-v2-09 | 23 | 6 / 17 | query_limit |
| heldout-v2-10 | 45 | 1 / 44 | media_attempts_limit |
| heldout-v2-11 | 37 | 14 / 23 | query_limit |
| heldout-v2-12 | 50 | 12 / 38 | target_reached |

留出实际覆盖：12例、8例空文字、4例动画输入，PNG/JPEG/WebP/GIF 四种输入。最少返回8条，最多50条；不足数量未剔除。Top10 使用固定10分母，缺失位置不能缩小分母。未审阅时相关性及视觉重复率为 unknown，而不是0%或100%。

## 性能与调用

15例 API 首批已验证草稿可见：p50 28.5秒、p95 36.045秒（观测 n=15）。任务内耗时 p50 120.046秒、p95 128.103秒。客户端全流程含证据下载/解码/DB核对：p50 123.45秒、p95 129.993秒。不是浏览器首屏渲染基准或严格因果加速实验。

正式15例记录模型调用尝试 45 次、搜索调用尝试 69 次。不估造实际账单费用。

## 网页与核验对照

当前正式网页 job `f43dff56-145b-4059-9eb7-e2cbf466a223`，实际50条。分页candidate ID、筛选数量、刷新位置、动静态文件 SHA/DB、真实动画像素变化、暂停/离屏暂停、懒加载及移动滚动全部通过，无脚本错误。对照后恢复 verify=true，另一个5条真实任务确认运行 worker 已开启核验；原网页任务的 revision/50条结果在重启后仍保留。

两个同代码、同输入/预算的实际开关对照：A关闭、B开启均各返回50条，A每例2次模型调用、B每例3次。配对时序和模型/网页随机性未受控；没有人审标签，不宣称核验提高质量。对照A的100条、网页50条、恢复检查5条均不并入正式575条。

## 交付入口

- 本地统一入口：`.cache/meme50/acceptance/hkust-deepseek-runtime-20261112/inspection/index.html`。
- 真实开发审阅：`frozen-v8/review-development/index.html`，150条。
- 真实留出审阅：`frozen-v8/review-heldout/index.html`，425条。
- 开关对照：`comparison-v8/index.html`，额外A臂100条及完整配对记录。
- 复现包：`meme50-v8-reproduction.zip`，约11.7MB；代码归档、固定输入、说明与未签署模板，不含真实凭据、权重或数据库。

以上相对目录都位于 `.cache/meme50/acceptance/hkust-deepseek-runtime-20261112/`。审阅页点击 Load / play 才载入原图/动画；真实页面已在 Chrome 检查图像和控件，所有标签仍 unreviewed、reviewer空白。操作见 [人审与复现说明](meme50-human-review.md)。

## 修复与限制

保留旧失败；核验查询的 [128字符上限见官方接口](https://api-docs.deepseek.com/api/search/)。本轮修复了页面获取延迟首批、大小图/时序及静态跨格式分组、真实 Tenor 原帖/相关卡片出处、HTML空属性、1像素RGB通道推断、实体名被128字符核验查询截掉、宽泛视觉实体角度丢失及前端导航竞态。未降低0.55排序门槛或扩充共享请求预算。预筛的名字、查询、URL均未传入正式请求；名字来自实际识图/规划并带确定或假设状态。

留出沿用固定字节，早期通用边界错误后的复测范围如实保留，不声称从未执行过这些输入。预筛有Tenor来源偏倚。字节/算法组唯一不能证明视觉无重复，仍需真人检查裁剪、循环及字幕含义。部署为当前宿主机API/独立worker加Docker PG/fetch；实际交付worker镜像已验证非root/只读与图文推理、fetch健康，但未宣称完整容器API/队列栈已经实测。

完整验收只有在真实标签满足Top10宏平均≥90%、返回列表明确相关宏平均≥80%、视觉重复为零，并完成另一位成员复现后才能通过。当前这些结论尚未签署。

代码指纹 `abd98e4acae985fa1aa80b21185f704fe30da83cd3e1331f4fc087baf9bf1732`；配置指纹 `c40faa19cc79414c4554e3f32c96dd9d137a54d8bb60610f80a0ef3935049291`。机器门槛原始结果：`frozen-v8/final/final.json`，退出码2。脱敏结构化汇总：[JSON](evidence/meme50-v8-acceptance-20261112.json)。历史过程见 [执行记录](meme50-live-20261112.md)。
