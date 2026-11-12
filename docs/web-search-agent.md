# Web searching agent 开发与交接

本页以下描述 legacy 文字规划、三 GIF 候选流程。新正式网页默认使用 [meme50-v2](meme50.md)：图片必填、文字可选，代表帧实际外发至配置的视觉及反搜 provider。旧流程“截图不发送给模型”的描述不适用于 v2。新实现与真实验收状态见 [记录](meme50-verification.md)。

负责人：Jiongle He。实现日期：2026-11-09。入口为 `services.search_agent.search_web`，可以独立运行，也可由 Haoxuan 的 worker 调用。它支持真正的网页搜索和图片搜索、查询规划、最多一次补搜、共享预算、来源去重及执行记录。

默认输出是网页或图片来源，`result_kind=sources`。只有接入 YuanJian 的动画验证与视觉排序函数后，才会输出 `result_kind=candidates`。搜索到 GIF 页面不等于已经获取原 GIF。截图不会发送给查询模型；当前联网查询使用用户补充的描述。

**资源选型**

| 资源 | 可复用能力 | 本版使用方式 |
| --- | --- | --- |
| [DDGS](https://github.com/deedy5/ddgs) | MIT 的 Python 元搜索库，提供网页及图片结果 | 可选开源入口，固定 `ddgs==9.16.1`，无需搜索 key；依赖上游站点可用性 |
| [SearXNG](https://github.com/searxng/searxng) / [API](https://docs.searxng.org/dev/search_api.html) | AGPL-3.0 的自托管元搜索，支持 JSON 和图片分类 | 已实现适配器；需要自己配置开启 JSON 的实例，不默认使用公共实例 |
| [DeepSeek Search](https://api-docs.deepseek.com/guides/search/) | 独立的托管网页搜索 API，复用 DeepSeek key | 本机已真实验证；默认 web 模式有 key 时选用。搜索与模型规划分别计费，均有调用上限 |
| [Brave Search](https://api-dashboard.search.brave.com/api-reference/images/image_search) | 托管网页与图片搜索，区分来源页和图片地址 | 已实现适配器；图片模式有 key 时自动选用，本机暂无 key |
| [Tavily](https://github.com/tavily-ai/tavily-python) / [API](https://docs.tavily.com/documentation/api-reference/endpoint/search) | MIT SDK 和托管搜索，可返回网页及关联图片；官方提供有限额 keyless 模式 | 通过 httpx 自主适配，不引入 SDK；限额明确返回失败 |
| [smolagents](https://github.com/huggingface/smolagents) / [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | 开源 agent 编排和工具调用 | 可作为后续扩展参考；本版两轮编排直接使用 Python 与 httpx |
| [browser-use](https://github.com/browser-use/browser-use) / [Crawl4AI](https://github.com/unclecode/crawl4ai) | 浏览器交互与网页抽取 | 待具体来源需要页面交互或解析时评估，不作为本版运行依赖 |

本版按官方协议自主实现适配器，没有复制上述项目代码。框架、搜索索引和文件抓取各有独立职责；搜索 API 不承诺返回目标原 GIF。

**安装与运行**

在仓库根目录使用 Python 3.11：

```powershell
uv pip install --python .venv/Scripts/python.exe -e ".[dev,search]"
.venv/Scripts/python.exe -X utf8 -m services.search_agent "小狗坐在着火的房间里说没事" --out .cache/web-search-agent/result.json
```

没有 uv 时，新建普通 venv 后使用 `python -m pip install -e ".[dev,search]"`。`search` extra 只增加 DDGS；其他适配器使用已有 httpx。

将 [配置示例](../experiments/meme_search/search-agent.env.example) 所需字段写到本机被忽略的 `.env`。现有 `DEEPSEEK_API_KEY` 可以直接复用，模型默认沿用 `DEEPSEEK_MODEL`；key 不进入输出。自动选择只在启动时确定一个 provider：web 模式有 DeepSeek key 时使用 DeepSeek，否则使用 DDGS；images 模式有 Brave key 时使用 Brave，否则使用 DDGS。不会因失败自动切换付费供应商。

```powershell
# 开源入口，禁用模型规划，直接以描述发起网页搜索
.venv/Scripts/python.exe -X utf8 -m services.search_agent "熊猫头大笑表情" --provider ddgs --mode web --no-model

# 图片发现；返回候选地址，尚未下载或确认动画
.venv/Scripts/python.exe -X utf8 -m services.search_agent "This is fine original gif" --provider brave --mode images

# 自托管 SearXNG，需要 .env 中的 SEARXNG_URL
.venv/Scripts/python.exe -X utf8 -m services.search_agent "熊猫头大笑" --provider searxng --mode images
```

DeepSeek Search 仅支持 web；显式选择 DeepSeek 配合 images 会返回配置错误。DDGS 和托管搜索可能被限流或超时，这些情况返回非零退出码及结构化错误。退出码为零只代表本次搜索流程完成，实际结果见 `result_kind`。

**worker 调用与候选接口**

```python
from services.search_agent import SearchBudget, search_web

result = search_web(
    image_path=input_image,
    description=user_description,
    work_dir=job_attempt_directory,
    budget=SearchBudget(timeout_seconds=60, max_rounds=2, max_downloads=6),
    prepare_candidates=your_candidate_processor,
)
record = result.model_dump(mode="json")
```

`job_attempt_directory` 必须是本次任务尝试的专用目录。YuanJian 提供 `prepare_candidates(image_path, sources, work_dir, budget)`，其中 `sources` 是包含 `title/source_url/image_url/snippet/provider` 的字典列表；`budget` 是只读 `CandidateBudget`，含整个任务剩余下载数量和 monotonic 截止时间。

处理器返回 `PreparedBatch` 或等价字典：`candidates`、`failures`、`downloads_used`、`model_version`。失败下载也消耗额度。候选字段固定为 `relative_path`、`sha256`、`source_url`、`image_url`、`provider`、`format='GIF'`、`frame_count>1` 和有限 `score`。文件先写入传入目录，路径相对该目录；agent 自动隔离各轮目录，并将返回路径转换为相对整个 job 目录。agent 检查路径和哈希，真实解码与视觉评分由处理器负责。同一任务禁止混用不同视觉模型的排序分数。

`failures` 使用安全代码：`static_image`、`not_gif`、`invalid_media`、`unsupported_source`、`download_failed`、`download_timeout`、`source_unavailable`、`model_unavailable`、`embedding_failed`、`storage_failed`。操作故障与正常媒体拒绝分开；全部下载失败会返回 failed，不能当作正常无匹配。模型只接收描述、已用查询和反馈计数，不接收网页中的指令或处理器自由文本。

当前 DeepSeek 的网页结果没有 `image_url`，用于来源发现；要进入动画处理链路，使用图片 provider，或后续加入来源页到媒体 URL 的解析工具。该解析工具、实际 GIF 验证和正式 API 接入都不能用默认 discovery 的成功代替。

最多两轮，每轮一次模型调用和一次搜索调用。整个任务最多尝试六个不同媒体地址，相同地址跨轮去重；默认获得一个已验证候选即可停止，最多返回三个候选。调用层与处理器遵守协作式截止时间；worker 仍需实现进程级硬超时和持久化 trace。同步第三方库可能超过单次网络 timeout，不能用本模块代替 worker 取消机制。

**验证证据**

2026-11-09 本机真实运行默认 DeepSeek 路径，一次模型规划、一次搜索返回六个网页来源，约 1.858 秒，无下载、无已验证 GIF；原始 JSON 在被忽略的 `.cache/web-search-agent/live-deepseek.json`。另一次直接 API 探测返回三个来源，包含 GIF 页面。它们只是连通性与来源发现验证，不是准确率实验。

同机 DDGS 多个上游超时，Tavily keyless 返回 HTTP 429 `daily_cap_reached`，Brave 未配 key，SearXNG 未部署。其余接口契约由模拟响应验证，不能称为全部供应商真实联网通过。

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_web_search_agent.py tests/test_web_search_providers.py
.venv/Scripts/python.exe -m ruff check services/search_agent tests/test_web_search_agent.py tests/test_web_search_providers.py
```

Jiongle 交付查询、来源适配、编排和 trace；YuanJian 接入处理器与多帧索引；Haoxuan 接入 worker、状态、硬超时与记录持久化；Zirui 将状态和结果接到统一页面。

## Recover original multi-frame GIFs

The recovery path uses the same `resolve_sources` and lazy-exported
`services.retrieval.prepare_candidates` in the CLI and formal worker runner.
Discovery remains the default. Supported sources and network limitations are in
[gif-source-support.md](gif-source-support.md); current acceptance evidence is in
[gif-acquisition-verification.md](gif-acquisition-verification.md).

Install Python 3.11 dependencies with `python -m pip install -e '.[dev,search,retrieval]'`.
Prepare weights explicitly with `python scripts/download_model.py`. Inference
uses local files only. Set the process's actual `MODEL_CACHE_ROOT`; a host
`data/models` directory does not populate the Compose named volume automatically.

```bash
python -m services.search_agent "用户对目标表情的自然描述" \
  --provider ddgs --mode web --no-model \
  --recover --image /path/to/authorized-screenshot.png \
  --work-dir .cache/gif-acquisition/case01-attempt01 \
  --out .cache/gif-acquisition/case01-result.json
```

Use a fresh work directory for each attempt. For the preferred DeepSeek path,
configure `DEEPSEEK_API_KEY` and pass `--provider deepseek --mode web` explicitly.
No paid provider is silently substituted. For an isolated direct-source check:

```bash
python -m scripts.verify_gif_acquisition \
  --source 'https://commons.wikimedia.org/wiki/File:Rotating_earth_(large).gif' \
  --image /path/to/authorized-screenshot.png \
  --out .cache/gif-acquisition/direct-attempt01
```

For real provider recovery, replace `--source URL` with `--description TEXT
--provider ddgs`. The verification tool exits nonzero unless verified candidates
are present. Its new output directory contains resolution/agent data, strictly
converted worker JSON, file hashes, elapsed time, and an implementation fingerprint.
`--use-model` explicitly enables the existing planner; it requires its configured
provider key and otherwise records the existing safe fallback warning.

Compose defaults now agree with local `web` mode. Set provider, mode, planner flag,
and threshold explicitly in the worker environment for reproducibility. Compose
passes `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL`, and `RETRIEVAL_MIN_SIMILARITY`.
The base URL/model settings govern the existing planner; DeepSeek Search retains
its existing official search endpoint. No new provider implementation is introduced.
The Docker `worker` target installs retrieval dependencies; API uses the lightweight
`api` final target. Container build and weight-volume availability must be verified
on a running Docker host.

Trace `resolve_sources` reports source hosts, logical page reads, redirects,
resolved media count, and controlled rejection reasons. `prepare_candidates`
reports logical media attempts, redirects, low-score rejections and failure codes.
The page ledger and media ledger persist across rounds. The formal runner removes
agent-only `sources` and validates `WebSearchResult` before writing one JSON object
to stdout; strict backend extra-field rejection remains enabled.

CI now runs `python -m pytest -q -m 'not smoke'`, including root-level agent tests.
Live network checks are explicit scripts, never part of ordinary CI. On macOS,
the unrelated caption-rendering regression requires `MEME_FONT_PATH` to an existing
font (for example `/System/Library/Fonts/Supplemental/Arial.ttf` for its English
fixture); deployment should retain a Chinese-capable font for Chinese captions.
