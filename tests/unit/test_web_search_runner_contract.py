import io
import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from services.common.search_schemas import WebSearchResult
from services.search_agent.models import SearchResult, Source
from services.worker.app import web_search_runner as runner


def result(**kwargs):
    return SearchResult(
        status="completed",
        result_kind="no_results",
        stop_reason="round_limit",
        sources=[Source(source_url="https://example.org/x", provider="fixture")],
        **kwargs,
    )


def test_actual_agent_json_requires_explicit_conversion():
    agent = result()
    with pytest.raises(ValidationError):
        WebSearchResult.model_validate_json(agent.model_dump_json())
    converted = runner.to_worker_result(agent)
    assert WebSearchResult.model_validate_json(converted.model_dump_json()) == converted
    assert "sources" not in converted.model_dump()


def test_entrypoint_export_is_lazy_in_fresh_process():
    code = """import sys
import services.retrieval as r
assert callable(r.prepare_candidates)
assert 'torch' not in sys.modules
assert 'transformers' not in sys.modules
assert 'services.retrieval.candidates' not in sys.modules
print('ok')"""
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert run.stdout == "ok\n"


def test_main_loads_real_export_and_resolver_and_emits_single_json(monkeypatch, capsys):
    import services.retrieval as retrieval
    from services.search_agent.resolvers import resolve_sources

    def search(**kwargs):
        assert kwargs["prepare_candidates"] is retrieval.prepare_candidates
        assert kwargs["resolver"] is resolve_sources
        return result()

    monkeypatch.setattr(runner, "search_web", search)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                dict(
                    image_path="input.png",
                    work_dir="work",
                    description="example",
                    max_downloads=6,
                    timeout_seconds=60,
                    call_timeout_seconds=12,
                )
            )
        ),
    )
    assert runner.main() == 0
    assert WebSearchResult.model_validate_json(capsys.readouterr().out).result_kind == "no_results"


def test_missing_processor_retains_safe_failure(monkeypatch, capsys):
    from types import SimpleNamespace

    monkeypatch.setattr(runner.importlib, "import_module", lambda _: SimpleNamespace())
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert runner.main() == 3
    assert json.loads(capsys.readouterr().out) == {"error_code": "candidate_processor_unavailable"}


def test_failed_candidate_combination_rejected():
    candidate = dict(
        relative_path="x.gif",
        sha256="a" * 64,
        source_url="https://example.org/x",
        image_url="https://example.org/x.gif",
        provider="fixture",
        format="GIF",
        frame_count=2,
        score=0.9,
    )
    with pytest.raises(ValidationError):
        SearchResult(
            status="failed", result_kind="candidates", stop_reason="error", candidates=[candidate]
        )
