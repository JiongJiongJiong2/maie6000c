import hashlib
import io
import json

import pytest
from PIL import Image

from scripts.prepare_demo import evaluation_examples
from services.common.reference_assets import AssetEntry


def test_local_examples_reuse_the_frozen_original_and_reject_changed_bytes(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(
        buffer, format="GIF", save_all=True, append_images=[Image.new("RGB", (16, 16), "blue")]
    )
    data = buffer.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    source = library / "test.gif"
    source.write_bytes(data)
    (library / "manifest.json").write_text(
        json.dumps({"assets": [{"sha256": digest, "gif_path": "test.gif"}]})
    )
    selection = {
        "assets": [
            {
                "id": "course-test",
                "sha256": digest,
                "title": "测试",
                "source_page": "https://example.org/test",
                "permission_note": "Generated for testing.",
            }
        ]
    }
    output = tmp_path / "reference"
    [asset] = evaluation_examples(library, output, selection)
    assert AssetEntry.model_validate(asset).sha256 == digest
    assert (output / asset["gif_path"]).read_bytes() == data
    assert evaluation_examples(library, output, selection) == [asset]
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        evaluation_examples(library, output, selection)
    assert (output / asset["gif_path"]).read_bytes() == data
