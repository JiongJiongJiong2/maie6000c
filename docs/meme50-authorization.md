# 线上检索的 DeepSeek 配置

本指南适用于引入个人 DeepSeek 配置的功能分支（首个实现提交 `6209ce4`）。部署者使用一把 `DEEPSEEK_API_KEY` 完成识图、OCR、查询规划、网页搜索、候选复核和可选的私人库 AI 标注。公开页面和图片从来源网站下载，多帧 CLIP 排序在本机执行。[官方视觉接口](https://api-docs.deepseek.com/guides/vision/) · [官方网页搜索接口](https://api-docs.deepseek.com/guides/search/)

在仓库根目录激活项目虚拟环境，再运行以下命令。第一条在本机终端隐藏输入密钥，直接回车会保留已有值；模型提示可回车采用显示的默认值。配置保存在本项目的私有 `.env` 文件中。

```shell
python -m scripts.configure_meme50 --deepseek-only
python -m scripts.configure_meme50 --check
```

检查输出应包含 `provider_policy=deepseek-only-v1`、`vision_provider=deepseek` 和 `deepseek_key_present=true`。这一步只读取配置，`authorization_verified=false` 是预期值。要验证实际服务权限，可通过网页使用一张公开样例提交新的联网任务，在 **Search activity** 查看结果。

更新配置后，宿主机部署请重启 API 和 worker。已有运行中的 Docker 部署请沿用原 Compose 项目名和全部 `-f` 参数，仅重建 API 和 worker 容器，使两者读取新的环境。在产品部署指南的 PowerShell 会话中可运行 `docker compose @product up -d --no-deps --force-recreate api worker`。[产品部署与 Compose 参数](product-deployment.md)

私人库的 **Analyze** 需要对所选 GIF 确认发送给 DeepSeek，每份最多发送四张抽样帧，画面中的文字也会随帧发送。已有学校网关的标注仍可查看；重新分析时须按网页提示重新同意。冻结的 `w13-final` 提交采用学校视觉网关。2026-11-28 的版本 `48f7693` 用 HKGAI 识图、DeepSeek 搜索，完成了地球 GIF 的网页与离线下载核验。[该版供应商与原件回执](../submissions/week13/browser-release-verification.json)

同一天在本机复现了缺少旧识图凭据的故障：两次任务均在任何网页搜索调用之前失败。实际切换到 DeepSeek 后，带来源提示的地球截图返回 43 个候选；从 Chrome 选机器人表情并点击继续联网，留空描述，页面返回 32 个候选，第一项可以下载。这两次均未找回已知原件。公开样本、模型版本、下载核验和耗时见[实测回执](evidence/gif-acquisition/deepseek-only-web-20261128.json)。

## 2026-11-12 的历史配置

2026-11-12 的版本使用学校 HKUST API 和个人 DeepSeek API，DeepSeek 默认模型为 `deepseek-flash`。

完整角色、管线与验收修订见 [执行说明](hkust-deepseek-execution.md)。此前 Google Vision / Brave 的失败记录是历史证据，不能继续作为当前目标的外部阻塞条件。

| 本项目私密配置 | 用途 |
| --- | --- |
| `MEME50_HKUST_API_KEY` | 学校 primary/secondary 任意一把，用于 HKUST 看图/OCR及证据复核；已配置并实际调用成功 |
| `DEEPSEEK_API_KEY` | 用户本人 DeepSeek key，用于 Flash 查询规划和官方网页搜索；已配置并实际调用成功 |
| `MEME50_HKUST_MODEL` | 默认 `gemini-2.5-flash-lite` |
| `MEME50_DEEPSEEK_MODEL` | 默认 **`deepseek-flash`** |
| `MEME50_PROVIDER_POLICY` | 固定 `hkust-deepseek-v1` |

检查配置（只输出布尔值和模型，不输出 key，不发请求）：

```bash
.venv/bin/python -m scripts.configure_meme50 --check
```

上述表格记录旧版配置。当时的学校视觉服务、自检命令和凭据角色以对应版本的运行说明为准。[旧版运行说明](hkust-deepseek-execution.md)

实际服务自检（每次输出目录必须全新）：

```bash
.venv/bin/python -m scripts.meme50_acceptance probe \
  --image .cache/meme50/inputs/dev-01.gif \
  --out .cache/meme50/acceptance/<新的目录>
```

旧版自检验证 HKUST 识图、DeepSeek Flash 规划、DeepSeek 网页召回及核验四类真实调用。个人 DeepSeek 版本使用相同的自检入口，四类调用都使用个人 DeepSeek 账户额度。

网页召回不等于以图反搜，也不等于得到五十个已校验表情。当前两个 API 不提供本流程的原始像素反搜通道，因此明确禁用该通道；相关性、数量、内容去重、正式网页、真实 DB、真人审阅与成员复现门槛保留。

学校及 DeepSeek 的实际调用会消耗各自账号已有额度，不代表所有调用免费；本轮没有新增计费账号、绑卡或购买服务。已有 Google Cloud 项目/密钥没有被删除，当前任务不再使用它们。
