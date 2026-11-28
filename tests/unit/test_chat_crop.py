import pytest
from PIL import Image, ImageDraw

from services.retrieval.chat_crop import propose_chat_crop


def _sticker():
    sticker = Image.new("RGB", (88, 74), "#bc9422")
    draw = ImageDraw.Draw(sticker)
    for x in range(0, sticker.width, 12):
        for y in range(0, sticker.height, 12):
            draw.ellipse((x + 1, y + 1, x + 10, y + 10), fill="#843d22")
    return sticker


def _screen(dark=False):
    base, panel, ink = ("#252530", "#39394a", "white") if dark else ("#dedee7", "#f6f6fb", "black")
    screen = Image.new("RGB", (260, 376), base)
    draw = ImageDraw.Draw(screen)
    draw.rounded_rectangle((12, 32, 248, 342), 8, fill=panel)
    draw.text((30, 48), "Tuesday 10:00", fill=ink)
    draw.text((36, 320), "Type a message", fill=ink)
    return screen


def _overlap(first, second):
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersect = max(0, right - left) * max(0, bottom - top)
    area = sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in (first, second))
    return intersect / (area - intersect)


@pytest.mark.parametrize(("dark", "origin"), [(True, (38, 92)), (False, (147, 223))])
def test_finds_sticker_off_center_in_light_or_dark_conversation(dark, origin):
    screen, sticker = _screen(dark), _sticker()
    x, y = origin
    screen.paste(sticker, origin)
    box = propose_chat_crop(screen)
    assert box is not None
    assert _overlap(box, (x, y, x + sticker.width, y + sticker.height)) > 0.8


def test_exif_coordinates_are_display_oriented_and_source_is_unchanged():
    screen = _screen()
    screen.paste(_sticker(), (140, 127))
    screen = screen.resize((520, 752))
    encoded = screen.transpose(Image.Transpose.ROTATE_90)
    encoded.getexif()[274] = 6
    box = propose_chat_crop(encoded)
    assert box == propose_chat_crop(screen)
    assert box is not None and _overlap(box, (280, 254, 456, 402)) > 0.75
    assert encoded.size == (752, 520) and encoded.getexif()[274] == 6


def test_abstains_for_two_similar_sticker_sizes():
    screen = _screen()
    screen.paste(_sticker(), (22, 88))
    screen.paste(_sticker(), (143, 191))
    assert propose_chat_crop(screen) is None


def test_abstains_for_text_only_or_already_cropped_sticker():
    assert propose_chat_crop(_screen()) is None
    assert propose_chat_crop(_sticker()) is None
    sticker = Image.new("RGB", (130, 126), "white")
    sticker.paste(_sticker(), (18, 9))
    ImageDraw.Draw(sticker).text((12, 100), "A sticker caption!", fill="black")
    assert propose_chat_crop(sticker) is None


def test_transparency_even_in_one_pixel_preserves_original():
    screen = _screen().convert("RGBA")
    screen.paste(_sticker(), (95, 90))
    screen.putpixel((1, 1), (0, 0, 0, 0))
    assert propose_chat_crop(screen) is None
