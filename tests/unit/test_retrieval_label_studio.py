from urllib.error import HTTPError

import pytest

from scripts.retrieval_label_studio import sync_tasks


def test_failed_response_after_commit_resumes_without_duplicate_labels(monkeypatch):
    tasks = [
        {"data": {"dataset_id": "set", "case_id": "q", "candidate_id": str(index)}}
        for index in range(45)
    ]
    labeled = {**tasks[0], "annotations": [{"id": 52}]}
    stored = [labeled]
    sizes = []

    def api(path, payload=None):
        if payload is not None:
            sizes.append(len(payload))
            stored.extend(payload)
            if len(sizes) == 1:
                raise HTTPError(path, 500, "response failed", {}, None)
            return {"task_count": len(payload)}
        if "/export?" in path:
            return stored
        return {"task_number": len(stored)}

    monkeypatch.setattr("scripts.retrieval_label_studio.time.sleep", lambda seconds: None)
    sync_tasks(api, 2, tasks)
    sync_tasks(api, 2, tasks)
    assert sizes == [20, 20, 4]
    assert [t["data"] for t in stored] == [t["data"] for t in tasks]
    assert stored[0] == labeled


def test_rejects_mismatched_media_before_importing():
    data = {"dataset_id": "set", "case_id": "q", "candidate_id": "a", "preview": "new"}

    def api(path):
        if "/export?" in path:
            return [{"data": data | {"preview": "changed"}}]
        return {"task_number": 1}

    with pytest.raises(ValueError, match="unexpected task data"):
        sync_tasks(api, 2, [{"data": data}])
