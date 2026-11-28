# MemeRetrieve · Week 13 delivery

English · [简体中文](README.md)

Jiongle He, Haoxuan Jiang, YuanJian Li and Zirui Huang built MemeRetrieve to find an original animated GIF from a screenshot. Users can save the recovered original to a private library and find it again locally. [Team responsibilities](../../docs/final-project-plan.md)

## Run the demonstration

Use Python 3.11 to prepare the 12 licensed reference GIFs, pinned CLIP model weights and multi-frame index. Apply the database migrations on first startup. On Windows, the native launcher supports PostgreSQL 16. A Docker PostgreSQL instance can also run alongside a host worker. [Setup and launch](../../docs/local-demo.md) · [Database and persistent volumes](../../docs/technical/database-and-vector-search.md)

The online demonstration requires a vision provider and DeepSeek. HKUST is the default. To select HKGAI, run `python -m scripts.configure_meme50 --provider hkgai --vision-only` in the project’s virtual environment. Query planning and web search share the project’s DeepSeek configuration. Run `python -m scripts.configure_meme50 --check` before starting the services. Each operator supplies their own authorized credentials. [Provider configuration](../../docs/guides/online-search.md)

1. Open `/web/`. Sign in if accounts are enabled, choose **Local only**, upload a screenshot and keep the results.
2. If the target is missing, select **Continue online** on the same page. Describe the image, movement or source you remember. The new job links back to the original request.
3. Filter for animation, play the candidate and download it. Compare the download with the target file’s independently recorded SHA-256.
4. Select **Confirm and save** and wait for indexing to finish. Retain the database, media and model directories when restarting the API and worker.
5. With external access disabled, sign in to the same account in a new browser session. Use **Local only** with another frame. Check the asset, rank and SHA-256 of the second download.

## Verification records

Release candidate `48f7693`, which included sharing and browser compatibility changes, completed the web flow again with an empty account. The target GIF ranked first online and first offline after restart. Both downloads matched the independent original byte for byte. The run returned 46 still images and four animations. Browser filter counts matched the database. Both the online candidate card and the offline saved card prepared the original GIF for the system share menu. [Release browser and download record](browser-release-verification.json)

On 28 November, the Chrome web app used HKGAI and DeepSeek to recover the 44-frame Earth GIF from Wikimedia Commons. The user provided the site and a description. Two searches used different frames. The original ranked first online, was saved and indexed, and ranked first locally after restart with outbound access disabled. Both downloads matched the independent 1,001,718-byte original. The record preserves the earlier Windows path failure and misses across six attempts. [Online and offline browser record](../../docs/evidence/gif-acquisition/hkgai-web-offline-20261128.json)

In the 12-GIF reference library, the first-frame index placed 11/12 targets in the top three and the multi-frame index placed 12/12 there. Each run used the same model, threshold of `0.82` and inputs taken about one third of the way through each GIF. The results include each file’s hash, frame, score and elapsed time. [Local results](local-corpus-evaluation.json) · [Evaluation method](../../docs/yuanjian-benchmark-guide.md)

The technical brief explains the engineering checks and retrieval limitations. The AI use statement identifies model responsibilities and verification methods. The team still needs to confirm the independent user screenshot hit rate, the other members’ reproduction sign-offs and the course submission receipt. [Technical brief](final-technical-brief.en.md) · [AI use statement](ai-use-statement.en.md)

## pgvector and product deployment

Checks covered logical restoration of the previous account database, backfill of saved GIFs, synchronization of 96 reference frames and isolation between accounts. After a 44-frame GIF was added through the web app, pgvector found it at rank one after an offline restart. The downloaded original was byte-identical. When a derived vector row for an old saved asset was removed, the NPZ fallback found that asset again. A public Noto reference sample verified a first-place hit and original download, and a separate search verified the no-candidate result. [Migration, offline lookup and download record](pgvector-verification.json) · [Product use and Docker deployment](../../docs/guides/product-deployment.md)

## Invite-only beta rehearsal

On 28 November, an isolated local installation passed the Chrome rehearsal. Registration returned 403 with an invalid invitation code and 201 with a valid code. Anonymous access to the private library returned 401. A screenshot from frame 13 of the imported, licensed 44-frame GIF ranked the asset first. After recreating the API and worker and signing back in through a fresh browser, frame 29 placed the same asset first again. Both downloads matched the 1,001,718-byte original. External search was disabled. External HTTPS access and retrieval quality for independent participants remain to be tested. [Beta rehearsal record](public-beta-rehearsal.json) · [Beta guide](../../docs/guides/public-beta.md)
