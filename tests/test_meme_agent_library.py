import io
import numpy as np
import pytest
from PIL import Image
from services.meme_agent.library import Library


def data(color):
    out = io.BytesIO()
    Image.new("RGB", (3, 3), color).save(out, format="PNG")
    return out.getvalue()


def encode(image):
    return np.array(image.getpixel((0, 0)), dtype=np.float32)


def test_save_dedup_restart_and_search(tmp_path):
    lib = Library(tmp_path, encode)
    first = lib.add_candidate(
        data("red"),
        {
            "title": "猫",
            "tags": ["开心"],
            "provider": "edit",
            "parent_id": "base",
            "caption": {"top_text": "hi"},
        },
    )
    saved, duplicate = lib.save(first["id"])
    assert not duplicate and saved["parent_id"] == "base"
    other = lib.add_candidate(data("red"), {"title": "duplicate"})
    assert lib.save(other["id"])[0]["id"] == first["id"]
    reopened = Library(tmp_path, encode)
    assert reopened.search("开心")[0]["caption"]["top_text"] == "hi"
    assert reopened.search(image=Image.new("RGB", (1, 1), "red"))[0]["score"] == pytest.approx(1)
    assert len(reopened.list_saved()) == 1


def test_failed_encoding_does_not_save(tmp_path):
    lib = Library(tmp_path, lambda image: np.zeros(3))
    item = lib.add_candidate(data("red"), {})
    with pytest.raises(ValueError):
        lib.save(item["id"])
    assert not lib.get(item["id"])["saved"]
    assert lib.list_saved() == []


def test_model_mismatch_and_public_data(tmp_path):
    def encoder(image):
        return encode(image)

    encoder.model_id = "v1"
    lib = Library(tmp_path, encoder)
    item = lib.add_candidate(data("red"), {"title": "red", "secret": "hidden"})
    lib.save(item["id"])
    encoder.model_id = "v2"
    assert lib.search(image=Image.new("RGB", (1, 1), "red")) == []
    assert "secret" not in lib.get(item["id"])
    assert "vector" not in lib.get(item["id"])
    lib.close()


def test_concurrent_instances_deduplicate(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    a, b = Library(tmp_path, encode), Library(tmp_path, encode)
    x = a.add_candidate(data("red"), {})
    y = b.add_candidate(data("red"), {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: pair[0].save(pair[1]), [(a, x["id"]), (b, y["id"])]))
    assert results[0][0]["id"] == results[1][0]["id"]
    assert sorted(result[1] for result in results) == [False, True]
    a.close()
    b.close()


def test_cleanup_retains_saved_parent(tmp_path):
    import json

    lib = Library(tmp_path, encode)
    parent = lib.add_candidate(data("red"), {})
    orphan = lib.add_candidate(data("blue"), {})
    child = lib.add_candidate(data("green"), {"parent_id": parent["id"]})
    lib.save(child["id"])
    for item in (parent, orphan):
        metadata = json.loads(
            lib.db.execute("SELECT metadata FROM items WHERE id=?", (item["id"],)).fetchone()[0]
        )
        metadata["created_at"] = "2000-01-01T00:00:00+00:00"
        lib.db.execute("UPDATE items SET metadata=? WHERE id=?", (json.dumps(metadata), item["id"]))
    lib.db.commit()
    lib.close()
    reopened = Library(tmp_path, encode)
    assert reopened.media_path(parent["id"]).is_file()
    with pytest.raises(KeyError):
        reopened.get(orphan["id"])
    assert not (reopened.files / orphan["id"]).exists()
    assert len(reopened.list_saved()) == 1
    reopened.close()
