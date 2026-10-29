# Design direction: Internet Lost & Found

Researched and implemented on 2026-10-28 for the request to make MemeRetrieve funny, playful, and visually expressive. All application copy remains in English.

## References and interpretation

| Reference | Observation | Applied direction |
|---|---|---|
| [Gumroad](https://gumroad.com/) | Its current homepage uses large typography, a strong contrasting accent, and floating illustrated objects. | Oversized headlines, a small high-contrast palette, and illustrated objects with strong silhouettes. |
| [Poolsuite](https://poolsuite.net/) | Its interface presents a music player as a nostalgic desktop window. | Window title bars, small monospace labels, and a deliberately tactile interface. |
| [GifCities](https://gifcities.org/) | The Internet Archive project searches animated GIFs from GeoCities. | A reference for the playful history of GIF culture and the idea of rediscovering something from the web. |
| [MDN: prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion) | The media query detects a user preference to reduce nonessential motion. | Respect the operating-system preference and also provide a persistent page-level motion control. |

These references informed the direction. No third-party illustrations, fonts, GIFs, layout templates, or site code were copied into the application. The mascot is an original inline SVG; other illustrations use CSS and native elements. The page makes no runtime requests for decorative assets and does not integrate a third-party GIF provider.

## Visual system

- Warm paper background, near-black ink, acid lime, lilac, and pink.
- Bold condensed-feeling headlines, close letter spacing, small monospace labels, solid outlines, and offset shadows.
- A rotated headline sticker and a collage of a screenshot, a goofy mascot window, and a circular label.
- A search workspace styled as two desktop windows: the uploaded clue and the candidate lineup.
- Three original characters illustrate the empty result state. Actual search candidates always come from the backend.

## Voice and interaction

The theme is a lighthearted missing-meme investigation. Supporting copy uses jokes such as "I was framed. Literally." and "No thoughts. Just loops." Errors and consequential actions retain direct labels, including upload, retry, accept/reject, and download.

The mascot follows the mouse within its illustration and responds to click, Enter, or Space with a different line. A successful acceptance produces one brief decorative confetti burst. A small star and slogan strip provide ambient motion; the Motion control stops them and stores only that preference in localStorage. The operating system's reduced-motion preference takes priority. No sound, cursor replacement, random movement of controls, or decorative network requests are added.

Decorative SVGs, stickers, the slogan strip, and confetti are hidden from assistive technology where appropriate. The interactive mascot has an accessible name and a live response. The skip link leads to the upload workspace. File selection, focus indicators, and keyboard operation remain available.

## Verification

The existing 14 browser checks still pass, including three tests against actual backend code with an isolated SQLite database and injected retrieval results. Five additional checks cover:

- Keyboard access to the mascot, persistent motion controls, and the operating-system reduced-motion preference.
- Three-candidate layouts and selecting the second candidate at 1440, 768, 390, and 320 pixels.
- No horizontal overflow, visible review/download controls, and suppressed confetti under reduced motion.

Desktop, tablet, and mobile screenshots were generated and inspected. Browser screenshots of candidate tests contain synthetic fixtures, not evidence of real model retrieval. The API contract, authentication, idempotency keys, local search recovery, and backend requirements are unchanged.

To run the design checks:

```bash
cd web
PLAYWRIGHT_CHANNEL=chrome npm test -- design.spec.js
```

To also save review images, set `WEB_VISUAL_DIR` to an absolute output directory. Omit `PLAYWRIGHT_CHANNEL` when using Playwright's installed Chromium. See [README.md](README.md) for the full verification and integration procedures.
