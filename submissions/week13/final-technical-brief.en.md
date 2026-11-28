# Technical summary and retrospective

English · [简体中文](final-technical-brief.md)

## User workflow and components

The user can start by searching a screenshot locally with multi-frame visual vectors. When they choose to continue online, the API persists a linked job. The worker calls the configured vision model to describe visible details and text. DeepSeek generates queries and uses its search interface to retrieve web pages. The media fetch service reads public sources. The pipeline checks file bytes, decodes animations, ranks by visual content and removes duplicates. User confirmation saves the original file. A background job builds its multi-frame index for subsequent local searches. [Architecture](../../docs/architecture.md) · [Original assets and vector data model](../../docs/technical/database-and-vector-search.md)

## Engineering results

The release candidate was tested with a fresh database, account and browser session. The target original ranked first both online and offline. The online job took 137.846 seconds, made two model calls and five searches, and attempted 66 media fetches. With the same source clue, it returned four animations and 46 still images. The result mix differed from the PR run. Both versions’ downloads were checked against the original kept beforehand. The web sharing check reached the point where the file was ready. A user still needs to confirm sending or import in the target mobile app. [Release record](browser-release-verification.json)

In the 28 November Chrome test, the first local query returned no candidates. The user continued online and supplied a source clue. HKGAI vision and DeepSeek search returned 50 decoded media files, including 17 animations. The independent reference GIF ranked first. This job took 169.414 seconds, with five searches, two model calls and 87 attempts to fetch original media. Once eight saved frames had 512-dimensional vectors, external fetching was disabled and the services restarted. A new browser session searched another frame offline and again found the original first. [Run record and earlier misses](../../docs/evidence/gif-acquisition/hkgai-web-offline-20261128.json)

For the licensed 12-GIF reference set, changing only which frames were indexed recovered one additional target in the top three compared with first-frame indexing. Both runs included cold model startup. An independent screenshot set would be needed to estimate real-user success. [Per-case results](local-corpus-evaluation.json)

An earlier online job shipped to the development branch returned 48 media files, including 25 animations. Their formats, frame counts, download hashes and database rows were checked individually. On 27 November, an actual DeepSeek API run also covered the 44-frame original, indexing after saving and the offline web download after restart. [Media checks](../../docs/meme50-dedup-fix-20261113.md) · [27 November run](../../docs/evidence/gif-acquisition/deepseek-offline-reuse-20261127.json)

## Problems encountered

On Windows, the account directory, job UUID and content hash made the path long. The atomic writer previously repeated the full content hash in its temporary filename, exceeding the Windows path limit even when the destination itself was valid. It now uses a short random temporary name in the destination directory and atomically replaces the file there. In a UTC+08:00 PostgreSQL session, replacing the timezone on a returned timestamp with an explicit offset previously undercounted elapsed time by eight hours. Durations now use the actual difference between instants.

Public search can return visually similar animations, alternate resolutions or still images. For the demonstration, success meant a match to the target SHA recorded before the search. Model-generated queries had sometimes dropped the user’s source or animation request. The planner now reserves room for those clues within the existing query budget. Report the reproducible engineering case and independently judged user tasks separately. [Evaluation criteria and responsibilities](../../docs/final-closeout-plan.md)

## Release scope

The web app downloads original GIFs. Web Share depends on the device supporting the file type, and the user confirms the send in the receiving app. Direct WhatsApp import has a separate experimental entry point. The client-specific results for WeChat and QQ are recorded separately. [Browser compatibility](../../docs/yuanjian-web-compatibility.md) · [WhatsApp experiment](../../docs/whatsapp-web-import-experiment.md) · [WeChat investigation](../../docs/wechat-gif-sharing-investigation.md) · [QQ investigation](../../docs/qq-import-feasibility.md)
