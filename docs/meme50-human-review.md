# 当前冻结版本的真人验收

本页是操作说明，不是已经签署的审阅或成员复现。所有标签默认未审阅；模型、执行 agent、内部回归都不能代替真人相关性判断。

## 审阅当前真实产物

当前版本：`meme50-evaluation-v8-entity-priority-20261112`。目录根：`.cache/meme50/acceptance/hkust-deepseek-runtime-20261112/frozen-v8/`。

- 开发页：`review-development/index.html`，3 个预筛资源案例；结果总数以 cases.json 为准，来自各自独立单次任务。
- 留出页：`review-heldout/index.html`，在 12 例全部运行结束后生成。未生成前不能填写成已完成。

在浏览器打开本地 HTML。每个案例先看输入与可选文字，再逐条选择明确相关、部分相关或无关；静态及动态均按真实内容判断。动画需要播放，不只看封面。另行标记媒体有效性、低质量和重复状态；同一素材不同尺寸、压缩、帧率、循环或裁剪不能占多个独立名额。不同动作或有实质意义的字幕修改可按实际内容区分。

算法 content_group_id 只是提示，不能当作“无重复”的人工结论。疑似重复素材填写相同 duplicate_group，分歧写 notes；填写实际 reviewer 后导出 labels.csv。不要修改绑定的 case、job、revision、candidate、rank、SHA 字段。不同 attempt 的标签不能互相套用。部分填写可以保存，但全量质量指标仍 pending。

将导出的标签保存到单独文件，再在仓库执行（输出目录必须尚不存在）：

```bash
.venv/bin/python -m scripts.meme50_acceptance score \
  --manifest docs/meme50-evaluation-v8.json \
  --runs .cache/meme50/acceptance/hkust-deepseek-runtime-20261112/frozen-v8/development \
  --labels /absolute/path/development-labels.csv \
  --out .cache/meme50/acceptance/human-scores-development-v8
```

留出使用对应 heldout 目录和标签。所有 12 例均在分母中，技术失败、零结果或不足数量不能删掉。Top10 明确相关宏平均门槛 0.9，返回列表明确相关宏平均门槛 0.8，内容重复为零；三个资源充足案例的预筛及独立数量验收另判。

## 另一位成员的独立复现

审阅目录中的 `reproduction-template.json` 保持空白，必须由真实成员在其明确独立启动环境中填写，不能把执行 agent 第二次运行或容器内部检查当作另一位成员。

使用 baseline/code.tar.gz 中的同一代码版本，按 `meme50.md` 和 `hkust-deepseek-execution.md` 配置其受保护环境。真实学校与 DeepSeek key 不放进复现记录、命令参数、压缩包或聊天；不复制包含 key 的环境文件作为交付。复用其他环境时说明模型、DB、fetch、API 和 worker 的实际运行位置，避免启动两个队列消费者。

至少独立运行一例空文字真实任务，并使用正式网页核对分页、动静态下载 SHA、播放和刷新。保存实际 verify_meme50 evidence；记录真实操作者、日期、代码/配置指纹、输入 SHA、job/revision、运行命令、结果数量和遇到的问题。模板的 human_attestation 与 independent_from_executor 仅在事实成立时填写 true。没有真实复现记录时 A8 保持 pending。
