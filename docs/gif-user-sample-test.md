# Three user GIFs — nine-candidate inspection

Run date: 2026-11-11, Hong Kong. Inputs are the three GIF files explicitly supplied by the user. A local frame at one third of each animation was used for CLIP. Screenshots stayed local; user GIF bytes were not sent to a remote model.

This is a GIF-input inspection run, not a blind screenshot benchmark. Initial visual-description queries and subsequent filename-semantic-assisted queries are both preserved. Multiple independent bounded attempts were needed because DDGS intermittently failed, initial DNS blocked Tenor, and early searches returned different animations. Final selection merges actual returned candidates across attempts with SHA deduplication and fixed threshold 0.82. It is not represented as one successful API/worker job.

| Input | Output candidates | Byte-exact match to supplied file |
| --- | --- | --- |
| bumble-bee-sus.gif | 3 | 2 |
| ishowspeed-dance.gif | 3 | 2 |
| nick-wilde-zootopia.gif | 3 | None; similar versions only |

All nine exported files are distinct by SHA, fully decoded multiframe GIFs, and original downloaded bytes. Some are native renditions of the same animation. Bee candidate 3 and Speed candidate 3 are low-score different-scene substitutes and are labeled accordingly; no human acceptance is inferred.

Artifacts: `.cache/gif-user-tests/review/index.html`, `nine-gifs.zip` (exactly nine GIF entries), `results.json` (scores/SHA/provenance/attempts), and `contact-sheet.png` (static first-frame QA). Raw attempts and failures remain under `.cache/gif-user-tests/`. The Speed cached-source follow-up is a separate diagnostic and not used to inflate the final nine.

New source support: Tenor `/view/...-ID` and localized equivalents; deterministic `store-cache` parsing selects only that exact post ID and its advertised GIF media formats. Static preview, MP4, and unrelated-post cards are excluded. HTTPS host registration is limited to `tenor.com`, `media.tenor.com`, and `media1.tenor.com`. Existing DNS/public-address, redirect, byte/decode, and deadline checks remain enabled. Distinct posts are prioritized before extra renditions, preserving at most two selected URLs per page and six media attempts per job.

Tenor material was retrieved for the user-requested local inspection; no open-media license is asserted. GIFs and screenshots are ignored local artifacts, not included in Git. Tests: 236 passed, 4 PostgreSQL tests skipped without TEST_POSTGRES_URL, 2 smoke deselected; Ruff/diff checks pass. This test does not replace the prior separate PostgreSQL acceptance record.

The final nine-file manifest distinguishes exact downloaded-byte matches from visually similar or wrong-scene alternatives. No user input file was copied into the candidate set.
