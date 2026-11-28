import io
import json
import subprocess
import sys

import httpx
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


@pytest.mark.parametrize("old_provider,key", [("auto", ""), ("brave", "operator-test-key")])
def test_live_runner_forces_official_deepseek_on_stale_environment(
    tmp_path, monkeypatch, capsys, old_provider, key
):
    from services.search_agent import core

    original_client = httpx.Client
    monkeypatch.setenv("SEARCH_AGENT_PROVIDER", old_provider)
    monkeypatch.setenv("SEARCH_AGENT_MODE", "images")
    monkeypatch.setenv("SEARCH_AGENT_USE_MODEL", "false")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.org/key-collector")
    monkeypatch.setenv("BRAVE_API_KEY", "old-key")
    monkeypatch.setenv("MEME50_DEEPSEEK_API_KEY", key)
    calls = []
    for alternate in ("BraveProvider", "DDGSProvider", "SearxngProvider", "TavilyProvider"):
        monkeypatch.setattr(core, alternate, lambda *a, **kw: pytest.fail("alternate provider"))

    def handle(request):
        assert key and request.headers["Authorization"] == "Bearer " + key
        assert request.url.host == "api.deepseek.com"
        calls.append(request.url.path)
        if request.url.path == "/chat/completions":
            answer = '{"action": "search", "query":"animated reaction"}'
            return httpx.Response(200, json={"choices":[{"message":{"content":answer}}]})
        assert request.url.path == "/v1/tools/search"
        return httpx.Response(200, json={"results":[]})

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    image = tmp_path / "input.png"
    image.write_bytes(b"unused by empty search")
    payload = dict(
        image_path=str(image), description="reaction", work_dir=str(tmp_path / "work"),
        max_downloads=6, timeout_seconds=40, call_timeout_seconds=4,
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert runner.main() == 0
    data = json.loads(capsys.readouterr().out)
    if key:
        assert set(calls) == {"/chat/completions", "/v1/tools/search"}
    else:
        assert not calls and data["status"] == "failed"


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
