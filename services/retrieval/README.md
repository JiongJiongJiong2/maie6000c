# MemeRetrieve — Retrieval Module (W07)

**Owner:** YuanJian Li  
**Module:** `services/retrieval/`  
**Status:** Working retrieval prototype; team-wide integration is not yet verified.

## 1. Purpose and current scope

This module retrieves an existing animated GIF from a cropped screenshot using pretrained image features. The current baseline samples GIF frames, encodes both corpus frames and a query with CLIP ViT-B/32, computes cosine similarity, and returns up to three **distinct GIF assets** ranked by their best-matching sampled frame.

**The three GIFs in `corpus_manifest.csv` are pilot/test fixtures only, not the final project corpus.** They were selected to test decoding, indexing, ranking and no-match behavior, not to demonstrate coverage of real-world memes. The W07 team plan targets **10–20 permission-cleared GIFs** for the integrated demo; the earlier W04 proposal's 50–100-GIF target is a longer-term plan. Corpus-based results must not be described as unrestricted Internet meme recovery.

No model training or vector database is used. The retrieval module does not own API requests, background-job state, database writes, candidate media endpoints, or web UI behavior.

## 2. Environment and model baseline

Locally verified on Windows with:

| Component | Version |
|---|---|
| Python | 3.11.18 (Conda environment: `maie6000c-retrieval`) |
| PyTorch | 2.9.1+cu128 |
| TorchVision | 0.24.1 |
| PyTorch CUDA runtime | 12.8 |
| Transformers | 4.57.1 |
| Pillow | 11.3.0 |
| NumPy | 1.26.4 |
| pytest | 8.4.1 |
| GPU | NVIDIA GeForce RTX 3060 Laptop GPU |
| Pretrained encoder | `openai/clip-vit-base-patch32` |

Install the GPU build used for local verification (in an activated Python 3.11 environment):

```cmd
python -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128
python -m pip install transformers==4.57.1 Pillow==11.3.0 numpy==1.26.4 pytest==8.4.1
python -m pip check
```

The code selects CUDA when available and falls back to CPU. **CPU execution and team Docker deployment have not been benchmarked or validated here.** The first model load requires access to the pretrained weights; cached weights are reused locally and are **not** committed to Git.

### Can the encoder be replaced later?

**Yes, at the architectural level.** CLIP ViT-B/32 is a first baseline, not an unchangeable project requirement. However, the current implementation is **not a plug-and-play model switch**: `encoder.py` loads a CLIP-specific processor and model, and `prepare_corpus.py` / `search.py` currently validate **512-dimensional** embeddings.

To use a different pretrained image encoder later:

1. Update `encoder.py` to load the new model and processor, and produce normalized image vectors.
2. Adjust feature-dimension checks and any model-specific assumptions in indexing/search/tests.
3. Rebuild **all** corpus embeddings with the new model and preprocessing. Query and corpus features must be produced by the same encoder version; do not mix old and new vectors.
4. Change/record `model_version` (including a pinned model revision if strict reproducibility is needed), update the corpus/index version, and reevaluate ranking and the no-match threshold on appropriate data.
5. Preserve the agreed public `search(image_path, top_k=3)` return contract, or coordinate any change with the backend owner first.

## 3. Test GIF Corpus

The current corpus contains three GIFs from Wikimedia Commons, used only for initial testing. All are CC0 or public-domain assets.

| GIF | License |
|---|---|
| `winking_smiley.gif` | CC0 1.0 |
| `smiley_bounce.gif` | Public Domain |
| `red_balloon.gif` | CC0 1.0 |

The `corpus_manifest.csv` records each asset's fixed UUID, source URL, and license.

Team members can download the original GIFs from the source URLs and save them using the filenames in the manifest. **Everyone must reuse the same UUIDs** so retrieval results match backend database records.

GIF binaries and model caches are not committed to Git. The corpus will be expanded for later milestones.

## 4. Build the pilot index

From the repository root, in Windows CMD with the retrieval environment activated:

```cmd
python -m services.retrieval.prepare_corpus --gif-dir "..\retrieval_data\gifs" --manifest "services\retrieval\corpus_manifest.csv" --index-dir "..\retrieval_data\index" --corpus-version w07-v2
```

The script validates GIF animation, samples up to eight evenly distributed frames per asset, computes normalized CLIP features, checks duplicate IDs/file hashes, and writes:

```text
../retrieval_data/index/
  index.npz
  index_metadata.json
```

**Locally observed output:**

```text
Indexed winking_smiley.gif: 8 frames
Indexed smiley_bounce.gif: 8 frames
Indexed red_balloon.gif: 7 frames
Done: 3 GIFs, 23 frame embeddings
```

Index shape: `(23, 512)`; unique GIF IDs: `3`. Rebuilding from different assets, model weights, preprocessing, or sampling rules may change features and results. Preserve the UUID-to-file mapping for the backend database import.

## 5. Query and worker interface

Set the index location in the **same process environment** that runs retrieval:

```cmd
set "MEMERETRIEVE_INDEX_DIR=..\retrieval_data\index"
```

Optional pilot-only rejection threshold (no threshold is applied if unset):

```cmd
set "MEMERETRIEVE_MIN_SCORE=0.82"
```

`0.82` is an **experimental threshold from a tiny pilot**, not a calibrated production cutoff. It has not been frozen or evaluated on an independent held-out set.

Example CLI query (a test screenshot must already exist at this path):

```cmd
python -m services.retrieval.search --image "..\retrieval_data\queries\test_winking.png" --top-k 3
```

Worker-side call:

```python
from services.retrieval import search
result = search(image_path, top_k=3)
```

Response shape:

```json
{
  "matches": [
    {"reference_asset_id": "ab7755d6-0cf2-46f6-972c-869753f6c368", "score": 0.9937}
  ],
  "model_version": "openai/clip-vit-base-patch32",
  "corpus_version": "w07-v2"
}
```

The JSON above is an **abbreviated example**, not an exact transcript of the complete Top-3 response. Scores represent cosine similarity, **not probability of correctness**. `matches` may be empty. Model/file/index failures should be raised to the worker instead of disguised as no-match.

The retrieval module returns stable reference-asset IDs; it does **not** return browser media URLs. Haoxuan's worker/backend must map those UUIDs to persisted `reference_assets`, validate/cache actual GIF media, write candidates and job results, and expose the agreed API. Keep these boundaries unchanged unless a team-level contract update is agreed.

## 6. Actual verification evidence

**Real local inference:** CLIP successfully ran on `cuda` (RTX 3060), producing normalized 512-dimensional features.

**Pilot index:** 3 authorized GIFs, 23 frame embeddings.

**Three in-corpus test crops:**

| Query | Correct Top-1 cosine score | Result |
|---|---:|---|
| Winking Smiley | 0.993701 | Correct |
| Smiley Bounce | 0.982296 | Correct |
| Red Balloon | 0.994885 | Correct |

Observed pilot Top-1: **3/3**. These screenshots were derived from the known GIFs, so this is a pipeline sanity check, **not** generalization accuracy on real mobile screenshots.

**Out-of-corpus pilot:** One negative query scored at most `0.663922` with no filter. With `MEMERETRIEVE_MIN_SCORE=0.82`, it returned `matches: []`. The threshold is not yet reliable for other negative queries or harder positive crops.

**Automated unit tests:**

```cmd
python -m pytest --noconftest tests/unit/test_retrieval.py -v
```

Observed: **15 passed in 10.70 s**. These tests use mocked embeddings to verify ranking, deduplication, thresholds, invalid inputs, missing indexes, and frame sampling. `--noconftest` skips the shared FastAPI fixtures in this isolated environment; full repository CI was **not** established by this run.

## 7. Limitations and pending work

- Expand from 3 test GIFs to the W07 target of 10–20 permission-cleared assets; provide the complete distributed corpus and stable IDs.
- Test more real screenshot crops, resizing, compression, background/UI clutter, near-duplicate memes, and out-of-corpus images. Evaluate a threshold on development queries and then on separate held-out queries.
- Record inference/indexing latency and memory usage; GPU execution worked, but resource benchmarks are not yet reported.
- Pin exact model weights/revision and authoritative file checksums for strict cross-machine reproducibility.
- Verify actual Worker/PostgreSQL/API integration, GIF media playback/download, Docker shared volumes and CPU fallback. None is claimed complete here.
- Coordinate any modifications to common dependencies, Docker, `.env.example`, database schema or API/result contract with Haoxuan before changing shared files.

## 8. Handoff

**Owned here:** `services/retrieval/`, source/permission manifest, model/index preparation, `search()` logic, and retrieval evaluation evidence.

**Backend owner (Haoxuan):** import reference asset metadata with the *same UUIDs*, make GIF files accessible to worker and media routes, supply model/index paths at runtime, manage tasks and persistence, and validate the end-to-end job path.

**Milestone status:** Working standalone retrieval baseline; integration and deployment remain to be verified. This README documents only tests actually reported for the current local setup.
