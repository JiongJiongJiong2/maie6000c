from io import BytesIO

from PIL import Image, ImageDraw

from services.api.app.library_rank import prepare_query, rank
from services.common.library_frames import annotation_frames
from services.common.media import representative_frames


def gif(ending):
    frames = []
    for index in range(24):
        frame = Image.new("RGB", (80, 64), "white")
        draw = ImageDraw.Draw(frame)
        draw.rectangle((index, 5, index + 12, 20), fill="red")
        if index >= 22:
            draw.rectangle((4, 45, 75, 59), fill="black")
        frames.append(frame)
    if ending == "blank":
        frames.append(Image.new("RGB", frames[0].size, "black"))
    elif ending == "repeat":
        frames.append(frames[4].copy())
    file = BytesIO()
    frames[0].save(file, "GIF", save_all=True, append_images=frames[1:], duration=40)
    return file.getvalue()


def test_latest_visible_tail_survives_blank_or_repeated_final_frame():
    for ending in ("caption", "blank", "repeat"):
        data = gif(ending)
        _, old = representative_frames(data)
        assert all(record["frame_index"] < 22 for record in old)
        frames, records = annotation_frames(data)
        assert len(frames) == len(records) == 4
        assert records[-1] == {"frame_index": 23, "time_ms": 920}
        assert frames[-1].getpixel((12, 52)) == (0, 0, 0)


def test_short_gif_deduplicates_as_before():
    red = Image.new("RGB", (50, 50), "red")
    blue = Image.new("RGB", red.size, "blue")
    data = BytesIO()
    red.save(data, "GIF", save_all=True, append_images=[blue, red], duration=100)
    frames, records = annotation_frames(data.getvalue())
    assert len(frames) == 2
    assert [record["frame_index"] for record in records] == [0, 1]


def test_chin_and_thinking_query_rewards_both_actions():
    for query in ("托着下巴在想事情的表情", "托下巴想问题", "撑着下巴沉思"):
        prepared = prepare_query(query)
        with_pose, reasons = rank(prepared, "sample-08", {}, {"action_tags": ["托腮", "思考"]})
        only_thinking, _ = rank(prepared, "sample-25", {}, {"action_tags": ["思考"]})
        unrelated, _ = rank(prepared, "sample-26", {}, {"action_tags": ["鼓掌"]})
        assert with_pose > only_thinking > unrelated
        assert unrelated == (0, 0, 0, 0, 0)
        assert {"托腮", "思考"} <= set(reasons)
