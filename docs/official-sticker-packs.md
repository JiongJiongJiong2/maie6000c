# Official sticker pack finder

Open `/stickers/` on the MemeRetrieve server. The page is public even when My Library requires sign-in. Inside MemeRetrieve, **Official Stickers** in the workspace navigation opens the same catalog at `/web/stickers`. The bundled demo has two MemeRetrieve packs. **Try a sample** finds Pond Post from a compressed screenshot of a later animation frame. Visitors can also browse the directory, preview animations and download the demo originals in ZIP format.

Crop the screenshot to one sticker, including any text or artist signature printed on it. The finder checks the local catalog and searches the public web on a miss. The configured HKUST or HKGAI image recognition provider reads the resized image, then DeepSeek searches without a region filter. It uses original-language clues and public release announcements to refine uncertain names, and checks previews on sticker sites such as LINE, Kakao and GIPHY. A pickup or sharing page with visually matching artwork can appear under **Verified links**. **Candidate pages** can include related collections, community packs, announcements and app-specific pickup instructions. Their labels distinguish artwork matches from name, text, or collection matches.

Screenshots are held in memory for the request. They are never added to My Library or written to the search-job media store. Docker Compose runs `sticker-lookup` without access to the account database or media volumes. It uses the existing vision and DeepSeek credentials and the isolated public fetcher. In a native API deployment, point `STICKER_LOOKUP_URL` at a separately configured lookup service to enable the public-web step.

## Publish a brand collection

Keep a directory with `manifest.json` and the sticker originals. Use the [demo manifest](../sticker_packs/demo/manifest.json) as a starting point. Use media the publisher has authorized for this directory. Give each pack an ID, name, publisher, creator, description and permission note. Each sticker needs an ID, display name and path relative to the catalog directory. GIF, WebP, PNG, APNG and JPEG files can be indexed. A pack can hold up to 40 stickers and a catalog up to 400.

Use `channels` to define a separate acquisition action for each platform. Each entry needs an `id`, `label` and verified official HTTPS `url`. For example, a pack can link to a WhatsApp pack and to the publisher’s WeChat instructions. Use `archive: true` only for packs whose originals are approved for direct download. The ZIP limit is 24 MiB of original media per pack. An optional `example` path lets visitors try the finder with a publisher-approved screenshot. Omit `demo` for a brand collection.

Validate the directory before deployment.

```sh
python -m services.common.sticker_catalog /path/to/approved-catalog
```

Set `STICKER_PACK_ROOT` to that directory for a native server. For Docker Compose, set `STICKER_PACK_HOST_PATH` to the host directory. Compose mounts the catalog read-only into the API container. Restart or recreate the API after replacing the catalog. It builds the frame index on the first catalog request. Share `/stickers/` from the campaign site or QR code.

## Measure the campaign

Set `STICKER_PACK_EXPERIMENT=true` to assign first-time visitors randomly to the directory or to the directory with screenshot search. A first-party cookie retains their assignment for 30 days. With the experiment disabled, visitors always see the finder.

The workspace always offers screenshot search and reports its events separately with `variant="workspace"`.

The API’s existing `/metrics` endpoint reports two counters.

| Counter | Labels and meaning |
| --- | --- |
| `sticker_pack_events_total` | `variant` and `event`. Counts page views, catalog search outcomes and public lookup outcomes such as `web_matched` and `web_no_match`. |
| `sticker_pack_claims_total` | `variant`, `pack` and `channel`. Counts an official outbound redirect or a request that produced a ZIP response. |

For a pilot with a known target pack, compare the target pack’s claim actions per page view between variants. These are aggregate requests. Reloads and repeated clicks count again. External download completion, sticker installation and chat sends require confirmation from the platform.

## Demo illustrations

The four original demo illustrations in [the demo catalog](../sticker_packs/demo/manifest.json) were generated with the built-in ImageGen tool. Each cropped sprite was turned into a six-frame animated WebP. The sample JPEG uses a decoded frame from the resulting animation.

> Generate one square production sprite sheet for an indie sticker-pack finder demo. 2 columns × 2 rows, exactly four individual separated die-cut messaging stickers. True transparent background with generous transparent gutters at central axes and all edges, no panels, no text, no letters, no numbers, no watermark. Each sprite centered in its own equal quadrant and occupies about 70% of that tile. Top left: origami green frog with raised hand, large happy expressive dark eyes and subtle blush. Top right: same acid-lime green frog with a yellow mug at its mouth, eyes half closed. Bottom left: squat lilac portable robot with rectangular charcoal display, two cream eyes and one screw antenna raising two hands in celebration, two coral sparkles. Bottom right: same lilac robot on a tiny rounded coral skateboard, round orange propulsion marks. Design: hand-inked playful collectible kawaii stickers, broad dark aubergine outlines, broad off-white sticker cutline, small paper grain and subtle halftone, independent silhouettes, polished original character art, clearly readable at 100 px. Keep disconnected quadrant assets safely separated, genuine alpha outside each complete sticker.
