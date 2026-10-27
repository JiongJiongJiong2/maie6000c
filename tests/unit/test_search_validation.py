from __future__ import annotations

import signal
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.common.search_schemas import RetrievalMatch, RetrievalResult
from services.common.storage import MediaError, contained_path
from services.worker.app import search_worker
from services.worker.app import retrieval_runner


@pytest.mark.parametrize("scores", [[float("nan")], [float("inf")], [0.2, 0.9]])
def test_invalid_scores_and_ranking(scores):
    with pytest.raises(ValidationError):
        RetrievalResult(
            matches=[RetrievalMatch(reference_asset_id=uuid4(), score=score) for score in scores],
            model_version="model",
            corpus_version="corpus",
        )


def test_duplicate_and_excess_matches_rejected():
    match = RetrievalMatch(reference_asset_id=uuid4(), score=0.9)
    for matches in [[match, match], [match] * 4]:
        with pytest.raises(ValidationError):
            RetrievalResult(matches=matches, model_version="model", corpus_version="corpus")


def test_paths_cannot_escape_storage(tmp_path):
    with pytest.raises(MediaError):
        contained_path(tmp_path, str(Path("..") / "outside.gif"))


def test_retrieval_timeout_is_typed(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        del args, kwargs
        raise subprocess.TimeoutExpired("retrieval", 1)

    monkeypatch.setattr(search_worker.subprocess, "run", timeout)
    with pytest.raises(search_worker.RetrievalError) as error:
        search_worker.invoke_retrieval(tmp_path / "input.png")
    assert error.value.code == "retrieval_timeout"


def test_search_worker_shutdown_signals_set_stop_event(monkeypatch):
    stop_event = threading.Event()
    handlers = {}
    monkeypatch.setattr(
        search_worker.signal,
        "signal",
        lambda signum, handler: handlers.update({signum: handler}),
    )

    search_worker.register_shutdown_handlers(stop_event)

    assert set(handlers) == {signal.SIGTERM, signal.SIGINT}
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert stop_event.is_set()


def test_invalid_retrieval_response_is_typed(monkeypatch):
    def invalid_response(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='{"matches":[]}')

    monkeypatch.setattr(search_worker.subprocess, "run", invalid_response)
    with pytest.raises(search_worker.RetrievalError) as error:
        search_worker.invoke_retrieval(Path("input.png"))
    assert error.value.code == "invalid_retrieval_result"


def test_retrieval_discards_unneeded_subprocess_stderr(monkeypatch, tmp_path):
    match = RetrievalMatch(reference_asset_id=uuid4(), score=0.9)
    result = RetrievalResult(matches=[match], model_version="model", corpus_version="corpus")
    call_options = {}

    def completed(*args, **kwargs):
        del args
        call_options.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=result.model_dump_json())

    monkeypatch.setattr(search_worker.subprocess, "run", completed)

    assert search_worker.invoke_retrieval(tmp_path / "input.png") == result
    assert call_options["stdout"] == subprocess.PIPE
    assert call_options["stderr"] == subprocess.DEVNULL
    assert "capture_output" not in call_options


def test_retrieval_runner_keeps_import_output_off_result_stdout(monkeypatch, capsys, tmp_path):
    match = RetrievalMatch(reference_asset_id=uuid4(), score=0.9)
    result = RetrievalResult(matches=[match], model_version="model", corpus_version="corpus")
    input_path = tmp_path / "input.png"

    def search(path: Path, *, top_k: int):
        assert path == input_path
        assert top_k == 3
        print("model diagnostic")
        return result

    def import_with_diagnostic(name: str):
        assert name == "services.retrieval"
        print("import diagnostic")
        return SimpleNamespace(search=search)

    monkeypatch.setattr(retrieval_runner.importlib, "import_module", import_with_diagnostic)
    monkeypatch.setattr(retrieval_runner.sys, "argv", ["retrieval_runner", str(input_path)])

    assert retrieval_runner.main() == 0
    captured = capsys.readouterr()
    assert captured.out == result.model_dump_json() + "\n"
    assert "import diagnostic" in captured.err
    assert "model diagnostic" in captured.err
