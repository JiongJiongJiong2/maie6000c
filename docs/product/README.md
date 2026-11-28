# MemeRetrieve product overview

English · [简体中文](README.zh-CN.md) · [Documentation home](../README.md)

MemeRetrieve helps you recover the original animated GIF when all you have is a screenshot. Upload a crop, play the closest matches, and check the movement and captions. Once you save the right GIF to your private collection, a different frame can find it again. The download contains the original animation.

## Where a search runs

| Option | What happens to the screenshot | What the user sees |
| --- | --- | --- |
| **Local only** | The browser uploads the crop to the MemeRetrieve server. The server searches its reference GIFs and the signed-in account’s indexed collection. | Up to three candidates to play and review, or an empty result. On a hosted installation the server receives the crop even in local mode. |
| **Online search** or **Continue online** | On an installation with online search enabled and configured, the selected vision provider receives a resized image or representative frames. DeepSeek plans queries and searches the web. | The **Search activity** panel shows progress. Results can include still images and animations. Play a GIF before using **Confirm and save**. |
| **Invite-only beta rehearsal** | The operator runs the site on their own computer. Registration requires an invitation code, and the rehearsal configuration disables external search and AI annotation. | Testers can import a GIF, search by screenshot, sign back in and download the saved original. An operator can add a private feedback form. |

The regular installation initially selects online search; choosing **Local only** keeps that search on the server. **My GIF Library** supports batch import and stores saved originals under the user’s account. Once indexing finishes, the GIF can be found locally after a service restart. Instructions for running the site and using the controls are in the [user and deployment guides](../guides/README.md).

## Organize and reuse originals

You can add titles and tags, search the collection by text, review possible duplicates, and export or restore a backup. If the operator enables external AI annotation, you can select specific GIFs and confirm before sending sample frames for analysis. On devices that support sharing GIF files, **Share GIF** hands the original to the system share menu. The receiving app determines how it is sent or imported. [Private-library verification](../private-meme-library-p0-p1.md) · [Browser and sharing evidence](../../submissions/week13/browser-release-verification.json)

## What has been verified

The invite-only rehearsal used a licensed 44-frame Earth GIF. A screenshot from frame 13 ranked it first. After the API and worker restarted, a fresh browser signed in and found the same asset first using frame 29. Both downloaded files matched all 1,001,718 bytes of the reference. A separate online test recovered that GIF when the operator supplied a description and the source site. The record includes six earlier unsuccessful attempts. [Beta rehearsal record](../../submissions/week13/public-beta-rehearsal.json) · [Online search record](../evidence/gif-acquisition/hkgai-web-offline-20261128.json)

In the fixed 12-GIF reference collection, multi-frame search placed the target in the top three for 12 of 12 screenshots, compared with 11 of 12 using only the first frame. Each input came from its target GIF. Accuracy on independent chat screenshots with cropping, captions or occlusion remains to be measured. [Per-case results](../../submissions/week13/local-corpus-evaluation.json)

## Who might pay for it

The proposed first customers are creators and content operators who regularly need the exact version of a GIF from a collection they control. The plan tests whether they will pay for a hosted private library and assisted import. Pricing, conversion and renewal targets are hypotheses for a future pilot. [Business model and pilot design](business-model.md)

For implementation details, including account isolation, persistent originals, frame vectors and the NPZ fallback, see the [technical documentation](../technical/README.md).
