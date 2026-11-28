import numpy as np
import pytest
from PIL import Image

from scripts.evaluate_chat_crop import (
    paired_rows,
    read_image,
    sampled_cases,
    stress_cases,
    summarize,
)
from services.common.storage import sha256


def case_for(path, transform, box=None):
    return {
        "id": "01234567",
        "target_asset_id": "red",
        "family_id": "pack",
        "category": "in_library",
        "transform": transform,
        "image": path.name,
        "image_sha256": sha256(path.read_bytes()),
        "transform_parameters": {"image_box": box},
    }


def test_paired_same_jpeg_pixels_and_abstention(tmp_path):
    path = tmp_path / "query.jpg"
    box = (4, 5, 12, 11)
    source = Image.new("RGB", (20, 15), "blue")
    source.paste("red", box)
    source.save(path, quality=47)
    case = case_for(path, "occluded", box)
    seen = []
    encoded = []

    def abstain(image):
        seen.append(image.copy())
        return None

    def encode(images):
        encoded.extend(image.copy() for image in images)
        return np.array([[1, 0] if im.size == (8, 6) else [0, 1] for im in images])

    rows = paired_rows(tmp_path, [case], abstain, np.eye(2), ["red", "blue"], encode)
    with Image.open(path) as decoded:
        assert seen[0].tobytes() == decoded.convert("RGB").tobytes()
        assert encoded[1].tobytes() == decoded.crop(box).convert("RGB").tobytes()
    assert len(encoded) == 2
    assert rows[0]["auto"] == rows[0]["full"] == ["blue"]
    assert rows[0]["oracle"] == ["red"]
    assert rows[0]["proposal_iou"] is None
    assert summarize(rows)["in_library"]["all"]["oracle"]["gained_vs_full"] == 1
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Query bytes changed"):
        read_image(tmp_path, case)


def test_sampling_keeps_paired_assets_across_packs():
    cases = [
        {
            "target_asset_id": target,
            "category": "in_library",
            "family_id": target[0],
            "transform": style,
        }
        for target in ["a1", "a2", "b1", "b2"]
        for style in ["plain", "chat"]
    ]
    sample = sampled_cases(cases, 2)
    assert sorted(c["target_asset_id"] for c in sample) == ["a1", "a1", "b1", "b1"]


def test_independent_layout_pairs_share_tile_and_jpeg_makes_measurable_change(tmp_path):
    path = tmp_path / "tile.png"
    tile = Image.new("RGB", (50, 46), "cyan")
    tile.paste("darkred", (12, 12, 42, 42))
    tile.save(path)
    cases = stress_cases(tmp_path, [case_for(path, "tight_crop")], tmp_path / "stress")
    assert len(cases) == 4
    decoded = [read_image(tmp_path / "stress", c) for c in cases]
    box = cases[1]["transform_parameters"]["image_box"]
    assert decoded[0].tobytes() == decoded[1].crop(box).tobytes()
    assert decoded[1].size == decoded[2].size == decoded[3].size
    assert decoded[1].tobytes() != decoded[2].tobytes()
    assert decoded[2].crop(box).tobytes() != decoded[3].crop(box).tobytes()


def test_out_of_library_gains_count_false_returns():
    row = {
        "target_asset_id": "outside",
        "category": "out_of_library",
        "transform": "chat",
        "proposed_box": (0, 0, 1, 1),
        "full": [],
        "auto": ["wrong"],
        "oracle": [],
    }
    stats = summarize([row])["out_of_library"]["chat"]
    assert stats["auto"] == {"false_candidate": 1, "gained_vs_full": 1, "lost_vs_full": 0}
