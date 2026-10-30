# Meme search pilot protocol

Frozen before search execution, 2026-10-30 (Asia/Shanghai).

This is a small, assistant-authored **text-to-web-discovery** pilot, not a user
study, screenshot reverse-image search benchmark, or product release. Eight
constructed descriptions cover four international templates, two Chinese static
meme families, one Chinese animated meme, and one deliberately unusual description
whose real-world existence is unknown. The last case is exploratory, not a proven
negative. No private user images or text are submitted.

## Comparison

Each case has three frozen queries: the literal input, an ordinary rewrite, and a
rewrite following the bundled meme-search procedure. Two independent GPT-6.1-sol
agents receive only the input descriptions; the latter additionally receives the
procedure. Both use medium reasoning and do not browse or see target labels.
The procedure is supplied as instructions in this experiment; this does **not**
test automatic skill discovery/loading by a production runtime. Generation token
costs and latency are not exposed and will not be invented.

All arms use the same host `web.search_query` tool, one query per case, no domain or
recency filter, `response_length=long`. Evaluate the first five normal web results
in the tool's returned order. They are **web pages**, not an image-search ranking.
No query may change after observing results. Rotate arm order across cases to
reduce systematic timing effects. The host tool may apply its own retrieval or
caching behavior, which is outside this experiment's control. No MCP vs HTTP
causal claim is possible because the host does not expose the underlying provider.

## Labels and evidence

Record returned titles, URLs, brief snippets, query, tool elapsed time, and UTC
capture time. Preserve compact raw tool output locally for audit. Before searching,
the expected families are Drake Hotline Bling, Two Buttons, Distracted Boyfriend,
Disaster Girl, panda-head/真人脸 family, Jacky Cheung's 吃屎啦你 frame, and Wang
Jingze's 真香 animation. Family relevance does not establish exact-asset identity.
Case c05 deliberately has no unique target image. Case c08 has unknown ground truth.

Judge page discovery from result evidence; an explicit blank-template page is a
blank-page hit, an explicit matching animated-GIF page is a GIF-page hit. These do
not prove that a blank or animated file can be downloaded. Ambiguous evidence is
unknown, not a forced success. A second assessor reviews labels independently.
Both assessors are AI assistants; no human user acceptance is measured.

Report Top-5 family-page discovery and reciprocal rank separately from blank-page
and GIF-page discovery. Unknown and missing judgments stay visible. GIF and blank
metrics across every case are descriptive only; category and case results are
needed to interpret intent-specific success. Do not call the results accuracy on
real screenshots or infer a significant skill effect from eight selected cases.

## Media and reuse smoke checks

Inspect a bounded subset of returned source pages, then probe observed direct
media URLs with TLS verification and bounded downloads. Record HTTP errors,
content type, decoded format/dimensions/frame count, SHA-256 and evidence of an
actual blank image. Never infer animation from a `.gif` suffix alone. Any fetched
third-party media remains in ignored `.cache/meme-search-pilot`; publish only
source references and measurements, not a rehosted meme corpus. Downloadability
does not establish permission to modify or redistribute.

If permitted existing project corpus assets are used for a local indexing check,
report it as a separate controlled smoke test, not web-recovery performance or
human acceptance. Costs unavailable from the host remain unknown. Report search
call counts and observed time, not a fabricated dollar estimate.

## Execution and scope

Use the existing Python environment and an isolated experiment folder. No changes
to the production API, worker, database or UI. No accounts, purchases, paid-service
subscriptions, provider credentials or automatic publishing of user collections.
The user authorized committing and pushing this experiment on an independent
branch. Do not merge it into dev/main or include unrelated PPT files.
