"""Tail-aware sampling for private library annotations."""

from bisect import bisect_right
from io import BytesIO
from itertools import accumulate

from PIL import Image

from services.common.media import inspect_media


def annotation_frames(data: bytes):
    metadata = inspect_media(data)
    with Image.open(BytesIO(data)) as gif:
        durations = []
        for index in range(metadata.frame_count):
            gif.seek(index)
            durations.append(max(10, int(gif.info.get("duration", 100))))
        ends = list(accumulate(durations))
        total = ends[-1]
        middle = sorted({bisect_right(ends, total * (i + 0.5) / 3) for i in range(3)})
        tail_start = max(0, min(len(ends) - 2, bisect_right(ends, total * 0.75)))
        selected = []
        seen = set()

        def candidate(index):
            gif.seek(index)
            rgba = gif.convert("RGBA")
            rgba.thumbnail((768, 768))
            rgb = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba)
            rgb = rgb.convert("RGB")
            fingerprint = rgb.resize((64, 64)).tobytes()
            red, green, blue = rgb.getextrema()
            blank = red == green == blue and red[0] == red[1]
            return index, rgb, fingerprint, blank

        def select(item):
            index, rgb, fingerprint, blank = item
            if not blank and fingerprint not in seen:
                seen.add(fingerprint)
                selected.append((index, rgb))

        for index in middle:
            select(candidate(index))
        tail = None
        for index in range(tail_start, len(ends)):
            item = candidate(index)
            if not item[3] and item[2] not in seen:
                tail = item
        if tail:
            select(tail)
        if len(selected) < 4:
            for index in sorted({bisect_right(ends, total * (i + 0.5) / 8) for i in range(8)}):
                select(candidate(index))
                if len(selected) == 4:
                    break
        if not selected:
            index, rgb, _, _ = candidate(len(ends) - 1)
            selected.append((index, rgb))
    selected.sort(key=lambda item: item[0])
    return (
        [frame for _, frame in selected],
        [
            {"frame_index": index, "time_ms": ends[index] - durations[index]}
            for index, _ in selected
        ],
    )
