# 当前授权与配置：学校 API + DeepSeek Flash

2026-11-12，香港时间。用户最新要求：当前表情检索任务只用学校 HKUST API 和自己的 DeepSeek API，DeepSeek 默认 `deepseek-flash`。不再要求 Google Vision、Google 直连 Gemini、Brave、Tavily 或其他供应商账号。

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

如需本机重新填写：

```bash
# 只填学校 key，模型直接回车
.venv/bin/python -m scripts.configure_meme50 --vision-only
# 只填 DeepSeek key，模型直接回车
.venv/bin/python -m scripts.configure_meme50 --deepseek-only
```

密钥隐藏输入，空输入保留现值；只更新本项目 `.env`，拒绝 symlink、换行注入和并发覆盖，原配置其他行保持，写入权限为 0600。不要把 key 放进命令参数、聊天、截图、测试数据或 Git。普通测试屏蔽真实本机 `.env` 和凭据环境变量，测试配置文件只在临时目录使用受控值。

实际服务自检（每次输出目录必须全新）：

```bash
.venv/bin/python -m scripts.meme50_acceptance probe \
  --image .cache/meme50/inputs/dev-01.gif \
  --out .cache/meme50/acceptance/<新的目录>
```

它验证 HKUST 识图、DeepSeek Flash 规划、DeepSeek 网页召回及核验四类真实调用，不再请求 Google Vision/Brave。查询、调用、时间、字节等预算共享；key 非空不是服务授权通过。

网页召回不等于以图反搜，也不等于得到五十个已校验表情。当前两个 API 不提供本流程的原始像素反搜通道，因此明确禁用该通道；相关性、数量、内容去重、正式网页、真实 DB、真人审阅与成员复现门槛保留。

学校及 DeepSeek 的实际调用会消耗各自账号已有额度，不代表所有调用免费；本轮没有新增计费账号、绑卡或购买服务。已有 Google Cloud 项目/密钥没有被删除，当前任务不再使用它们。
