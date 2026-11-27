"""Render captions locally onto a verified static blank template."""

import io
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def _font(size: int, font_path: str = ""):
    candidates = [
        font_path or os.environ.get("MEME_FONT_PATH", ""),
        "C:/Windows/Fonts/msyhbd.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for name in candidates:
        if name and Path(name).is_file():
            return ImageFont.truetype(name, size)
    raise ValueError("未找到字体，请设置 MEME_FONT_PATH 指向支持中文的字体。")


def render_captions(path: Path, top_text: str, bottom_text: str, font_path: str = "") -> bytes:
    with Image.open(path) as original:
        if getattr(original, "n_frames", 1) != 1:
            raise ValueError("第一版仅支持静态空白模板编辑。")
        image = ImageOps.exif_transpose(original).convert("RGB")
    image.thumbnail((1600, 1600))
    if min(image.size) < 80:
        raise ValueError("图片过小，无法可靠添加文字。")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    margin = max(8, int(width * 0.035))
    for text, bottom in ((top_text, False), (bottom_text, True)):
        if not text.strip():
            continue
        for size in range(max(16, min(width // 10, height // 9)), 7, -1):
            font = _font(size, font_path)
            lines = []
            for paragraph in text.splitlines() or [text]:
                line = ""
                for char in paragraph:
                    if line and draw.textlength(line + char, font=font) > width - 2 * margin:
                        lines.append(line)
                        line = ""
                    line += char
                lines.append(line)
            wrapped = "\n".join(lines)
            stroke = max(1, size // 16)
            box = draw.multiline_textbbox(
                (0, 0), wrapped, font=font, stroke_width=stroke, spacing=3, align="center"
            )
            text_height = box[3] - box[1]
            if text_height <= height * 0.34:
                break
        else:
            raise ValueError("文字太长，请缩短后再试。")
        x = (width - (box[2] - box[0])) / 2 - box[0]
        y = height - margin - text_height - box[1] if bottom else margin - box[1]
        draw.multiline_text(
            (x, y),
            wrapped,
            font=font,
            fill="white",
            stroke_fill="black",
            stroke_width=stroke,
            spacing=3,
            align="center",
        )
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()
