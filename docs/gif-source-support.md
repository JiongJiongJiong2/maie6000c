# GIF source support

Updated after live acceptance on 2026-11-11 (Hong Kong).

**Current status:** production G1, real provider recovery and real PostgreSQL/API/
independent-worker transfer have passed for engineering inputs. They do not establish
human original-target acceptance. See the repair section in
[gif-acquisition-verification.md](gif-acquisition-verification.md).

The first-pass support table below describes the initial scope; the additions in
"Post-repair source and environment" are the current effective scope.

Initially verified 2026-11-11 (Hong Kong). This iteration depends on PR #8, still open at
verification time, and is based on `c34d9f6c55a1febbe78fcbf275baab70536424d7`.

## Initial registered source (historical first pass)

| Setting | Support |
| --- | --- |
| Search | Existing adapters unchanged; live run used DDGS / web / planner disabled because paid-provider keys were absent |
| Page host | `commons.wikimedia.org`, HTTPS port 443, `/wiki/File:` pages |
| Media host | `upload.wikimedia.org`, HTTPS port 443 |
| Extraction | Original-file `a.internal` GIF link; relative URL resolution, HTML entity decoding, preserved query parameters; ignores thumbnails and ordinary image tags |
| Direct references | Existing `image_url`, or a registered media-host `.gif` URL used as its own provenance |
| Sample | [Rotating earth (large)](https://commons.wikimedia.org/wiki/File:Rotating_earth_(large).gif), Marvel, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) option |
| Current production live status | DNS policy rejected reserved fake-IP answers; source adapter's successful production download is **not verified** |
| Other sites | Unsupported; search coverage does not imply download support or permission to save |

The captured original-link fixture is `tests/fixtures/commons_original.html`.
Its markup was extracted from the actual public HTML fetched during this run.
The full HTML and original GIF remain ignored local evidence.

This sample permits engineering validation with attribution. Rights and source
conditions must be reviewed per new file and target; Commons hosting alone does
not establish the license of every file. No login, paid download, guessed original
URL, video conversion, browser automation, or fabricated animation is used.

## Limits and network policy

- Job: at most two search rounds, six different media URL attempts, six logical
  page GETs, three returned candidates, and one shared monotonic deadline.
- Each page or media GET has at most three redirects; every destination is checked.
  Redirect counts are separate from logical page/media attempt counts.
- Pages: at most 2 MiB of decompressed response bytes. GIF bytes: at most
  `min(12 MiB, MAX_CANDIDATE_BYTES)`.
- GIF: 2–1000 fully decoded frames; at most 20 million canvas pixels and
  100 million canvas pixels multiplied by frame count. Shared storage validation
  remains authoritative. Original downloaded bytes are saved without conversion.
- HTTPS and port 443 only, no userinfo, registered hosts only, all DNS answers
  must be public, no environment proxy, automatic retry, or HEAD probe.
- DNS preflight does **not** pin the HTTP transport's actual peer. The ordinary
  HTTP client resolves again; this does not eliminate DNS rebinding. Keep the
  explicit trusted-host registry; arbitrary-host support requires controlled
  egress or a connection-pinning implementation.
- Deadlines are cooperative, including checks before GETs/redirects/stream reads
  and expensive model work. DNS, socket operations, or local inference can remain
  blocked until they return. The parent worker retains its hard process timeout.

Local DNS returned `198.18.0.9` for Commons and `198.18.0.10` for upload.wikimedia.org,
which belong to a reserved benchmark range. Rejection is intentional. Configure a
public-DNS/direct-egress worker environment to repeat live verification; do not
whitelist these addresses or disable private-address checks.

## Ranking and outcomes

The screenshot stays local. The fixed local CLIP revision and white-background
preprocessing are reused. Uniformly sample `min(8, frame_count)` frames, normalize
embeddings, and take the maximum frame cosine similarity. Reject nonfinite or zero
embeddings. Rank by descending score, then SHA for ties; deduplicate content before
Top 3. A batch encodes its screenshot once. `RETRIEVAL_MIN_SIMILARITY=0.82` is the
existing development starting point, **not** a validated real-meme threshold.

URL normalization removes fragments and lowercases scheme/host without discarding
query parameters. Core tracks media URLs across both rounds, independently from
page deduplication. Failed GETs consume media budget; preflight rejection does not.

Unknown hosts and pages without an original GIF are normal coverage misses.
Supported-source access failures, download errors, missing model weights, encoding,
and storage failures produce a failed job if no candidate survives. Low-score
rejection is normal no-results and is counted in trace. Partial success keeps
warnings; a fatal result never exposes successful-looking candidates. Discovery
sources alone never count as recovered GIFs.


## Post-repair source and environment

- Commons supports one controlled URI-path decode for namespace recognition,
  including `File:` / `File%3A` and case variants, without rewriting the actual
  request URL. Article pages and double-encoded namespace delimiters are rejected.
  Resolve `a.internal` hrefs against the final page address before media policy checks.
- Added `https://cultofthepartyparrot.com/` gallery resolver: only its explicit
  `data-src="/parrots/hd/originalparrot.gif"` is selected. Media access on this host
  is also restricted to that exact original-green GIF path. Unknown colored
  variants and unrelated GIFs are rejected, even when the host matches.
- The project's [LICENSE](https://github.com/jmhobbs/cultofthepartyparrot.com/blob/main/LICENSE)
  records Geiger Powell's permission for original-GIF use/adaptation and says
  the colorful version's origin is unknown. Website MIT is not used as media
  authorization. `parrotdad.gif` named in its LICENSE was not assumed identical
  to the differently named `dadparrot.gif`; that variant remains unsupported.
- Actual original-green download: 13,485 bytes, 128×128, 10 decoded frames, SHA
  `ecfacdf40753e363e4022f79ee48ddf55d6b3d537b6a6fa80929718b653b7022`.
- Registered-host DNS lookup failures and nonpublic DNS are `source_unavailable`
  for direct media as well as pages; GET-preflight failures consume zero attempts.
  Unknown hosts remain normal `unsupported_source` coverage misses.
- Internal diagnostics distinguish `dns_failed`, `dns_non_public`, URL policy,
  HTTP status, TLS/connection and timeout stages. Trace contains codes/statuses,
  never response bodies, auth headers or upstream instructions.
- Requests identify this public project in User-Agent; the initial anonymous
  course-only identifier received HTTP 403 from Commons. Certificate validation
  and all DNS/address/redirect/byte restrictions remain enabled.
- Explicit settings: `SEARCH_AGENT_DDGS_BACKEND` selects one existing DDGS backend;
  `SEARCH_AGENT_DOMAINS` is a JSON list of at most three domain-only constraints.
  Final host stack uses `yahoo`, `web`, planner disabled and
  `["cultofthepartyparrot.com"]`. Bing also succeeded, but has observed intermittent
  failures; no hidden provider switch or retry was added.
- Domain constraints are disclosed in actual queries. They add no target filename,
  URL, SHA or candidate fallback. Independent reference files are only compared
  after the agent/worker has produced its result.
- Clash persistent global Merge preserves prior rules and now excludes the four
  explicit review hosts from fake-IP allocation (Commons, upload, partyparrot,
  raw.githubusercontent). A backup was kept in its configuration directory.
  Reactivation and the actual service-socket config reload/cache endpoints were
  exercised. macOS still intermittently returns a stale Commons fake IP;
  mDNSResponder refresh requires an unavailable sudo password, which was not
  requested or bypassed. Host partyparrot resolution and acquisition are working.
- Verified alternative for Commons: the task-owned Docker worker with explicit
  `--dns 1.1.1.1`, ordinary production download code, nonroot UID 10001 and local
  read-only model weights. It returns public DNS and passes real GIF acquisition.
  This does not whitelist fake IPs or alter DNS results inside the application.

Reviewed source proposals (not qualified user cases) are in
[gif-acceptance-cases.json](gif-acceptance-cases.json). They retain missing screenshot
and human-confirmation fields rather than manufacturing acceptance inputs.

## User-requested Tenor sample inspection

A later test with three user-supplied GIFs adds Tenor view-post parsing, including
localized URL prefixes. Only the viewed numeric post ID's advertised `gif`,
`mediumgif`, and size-bounded fallback `tinygif` entries are eligible; at most two
renditions per page. Distinct posts precede alternate renditions when the six-media
budget is allocated. Registered media hosts are `media.tenor.com` and
`media1.tenor.com`; all existing network and actual-animation checks apply.

This source is used for the user's local inspection request and has no blanket
open-media license assertion. No embedded page API key is used. Public page metadata
is parsed deterministically; it is not passed to the planner. Source images and
GIF bytes are kept ignored. See [gif-user-sample-test.md](gif-user-sample-test.md)
for actual outcomes and the distinction between byte-exact matches, alternate
renditions and wrong-scene candidates.
