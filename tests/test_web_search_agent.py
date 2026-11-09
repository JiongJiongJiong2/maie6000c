import hashlib

import httpx
import pytest
from PIL import Image

from services.search_agent import SearchBudget, search_web
from services.search_agent.models import CandidateBudget, PreparedBatch
from services.search_agent.planner import PlannerError, QueryPlanner
from services.search_agent.providers import ProviderError
from services.search_agent.settings import SearchAgentSettings


def settings(**kwargs):
    return SearchAgentSettings(_env_file=None, search_agent_use_model=False, **kwargs)


def hit(name="a", **kwargs):
    return dict(
        title=name,
        source_url=f"https://example.org/{name}",
        image_url=f"https://example.org/{name}.gif",
        provider="fixture",
        **kwargs,
    )


class Provider:
    name = "fixture"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def search(self, query, limit, timeout):
        self.calls.append((query, limit, timeout))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def run(provider, **kwargs):
    return search_web(description="熊猫头大笑", provider=provider, settings=settings(), **kwargs)


def test_discovery_is_not_recovered_media():
    provider = Provider([[hit("a"), hit("b"), hit("c")]])
    result = run(provider)
    assert result.status == "completed"
    assert result.result_kind == "sources"
    assert result.candidates == [] and result.downloads_used == 0
    assert len(provider.calls) == 1


def test_revise_after_empty_results_and_deduplicate():
    provider = Provider([[], [hit(), hit()]])
    result = run(provider)
    assert len(provider.calls) == 2
    assert provider.calls[0][0] != provider.calls[1][0]
    assert len(result.sources) == 1


def test_error_is_different_from_empty_search():
    failure = run(
        Provider(
            [
                ProviderError("provider_unavailable", "Unavailable"),
                ProviderError("provider_unavailable", "Unavailable"),
            ]
        )
    )
    empty = run(Provider([[], []]))
    assert failure.status == "failed" and empty.status == "completed"
    assert failure.stop_reason == "provider_unavailable"
    assert "search_provider_unavailable" in failure.warnings


def test_malformed_and_private_references_filtered():
    private = hit("bad")
    private["image_url"] = "http://127.0.0.1/secrets"
    provider = Provider([[private, {"title": "broken"}], []])
    result = run(provider)
    assert not result.sources
    assert result.trace[1].details["rejected"] == 2


def make_candidate(work, source, name="a", score=0.8):
    path = work / (name + ".gif")
    Image.new("RGB", (2, 2), "red").save(
        path,
        save_all=True,
        append_images=[Image.new("RGB", (2, 2), "blue")],
        duration=100,
    )
    return dict(
        relative_path=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_url=source["source_url"],
        image_url=source["image_url"],
        provider="fixture",
        format="GIF",
        frame_count=2,
        score=score,
    )


def test_processor_feedback_and_shared_download_budget(tmp_path):
    image = tmp_path / "input.png"
    Image.new("RGB", (2, 2)).save(image)
    available = []

    def prepare(image_path, sources, work, budget):
        assert isinstance(budget, CandidateBudget)
        assert image_path == image
        available.append(budget.remaining_downloads)
        if len(available) == 1:
            return PreparedBatch(downloads_used=2, failures=["static_image", "download_failed"])
        return PreparedBatch(
            downloads_used=1,
            candidates=[make_candidate(work, sources[0])],
            model_version="fixture-multiframe",
        )

    provider = Provider([[hit("a"), hit("b")], [hit("b"), hit("c")]])
    result = run(provider, image_path=image, work_dir=tmp_path / "job", prepare_candidates=prepare)
    assert available == [6, 4]
    assert result.result_kind == "candidates" and result.downloads_used == 3
    assert result.stop_reason == "candidates_found"
    assert result.model_version == "fixture-multiframe"


def test_processor_error_exhausts_unknown_download_consumption(tmp_path):
    image = tmp_path / "input.png"
    image.touch()

    def broken(*args):
        raise RuntimeError("secret key must not be exposed")

    result = run(
        Provider([[hit()]]), image_path=image, work_dir=tmp_path / "job", prepare_candidates=broken
    )
    assert result.status == "failed" and result.search_calls == 1
    assert "secret key" not in result.model_dump_json()


def test_processor_cannot_exceed_download_budget(tmp_path):
    image = tmp_path / "input.png"
    image.touch()
    result = run(
        Provider([[hit()]]),
        image_path=image,
        work_dir=tmp_path / "job",
        prepare_candidates=lambda *args: PreparedBatch(downloads_used=7),
    )
    assert result.status == "failed" and result.downloads_used == 6


def test_no_downloads_after_budget_exhausted(tmp_path):
    image = tmp_path / "input.png"
    image.touch()
    result = run(
        Provider([[hit()]]),
        image_path=image,
        work_dir=tmp_path / "job",
        budget=SearchBudget(max_downloads=1),
        prepare_candidates=lambda *args: PreparedBatch(downloads_used=1),
    )
    assert result.stop_reason == "download_limit" and result.search_calls == 1


def test_processor_missing_candidate_file_is_rejected(tmp_path):
    image = tmp_path / "input.png"
    image.touch()

    def prepare(image, sources, work, budget):
        candidate = make_candidate(work, sources[0])
        (work / candidate["relative_path"]).unlink()
        return dict(candidates=[candidate], downloads_used=1)

    result = run(
        Provider([[hit()]]), image_path=image, work_dir=tmp_path / "job", prepare_candidates=prepare
    )
    assert result.status == "failed"


def test_download_failure_is_not_a_normal_no_match(tmp_path):
    image = tmp_path / "input.png"
    image.touch()
    result = run(
        Provider([[hit()]]),
        image_path=image,
        work_dir=tmp_path / "job",
        budget=SearchBudget(max_rounds=1),
        prepare_candidates=lambda *args: PreparedBatch(
            downloads_used=1,
            failures=["download_failed"],
        ),
    )
    assert result.status == "failed" and result.stop_reason == "media_processing_failed"
    assert result.warnings == ["candidate_download_failed"]
    assert any(e.details.get("failure_codes") == ["download_failed"] for e in result.trace)


def test_round_work_directories_are_isolated_and_empty_batch_keeps_model(tmp_path):
    image = tmp_path / "input.png"
    image.touch()
    directories = []

    def prepare(image, sources, work, budget):
        directories.append(work)
        if len(directories) == 1:
            return PreparedBatch(
                downloads_used=1,
                candidates=[make_candidate(work, sources[0])],
                model_version="clip-v1",
            )
        return PreparedBatch(downloads_used=1, failures=["static_image"])

    result = run(
        Provider([[hit("a")], [hit("b")]]),
        image_path=image,
        work_dir=tmp_path / "job",
        budget=SearchBudget(desired_candidates=2),
        prepare_candidates=prepare,
    )
    assert result.model_version == "clip-v1" and result.status == "completed"
    assert directories[0] != directories[1]
    assert result.candidates[0].relative_path.startswith("round-1/")


def test_different_visual_models_cannot_mix_scores(tmp_path):
    image = tmp_path / "input.png"
    image.touch()
    count = []

    def prepare(image, sources, work, budget):
        count.append(1)
        return PreparedBatch(
            downloads_used=1,
            candidates=[make_candidate(work, sources[0])],
            model_version=f"clip-v{len(count)}",
        )

    result = run(
        Provider([[hit("a")], [hit("b")]]),
        image_path=image,
        work_dir=tmp_path / "job",
        budget=SearchBudget(desired_candidates=2),
        prepare_candidates=prepare,
    )
    assert result.status == "failed" and result.model_version == "clip-v1"


def test_deepseek_queries_fit_provider_character_limit():
    provider = Provider([[], []])
    provider.name = "deepseek"
    search_web(description="a" * 200, provider=provider, settings=settings())
    assert all(len(query) <= 128 for query, _, _ in provider.calls)
    assert provider.calls[0][0] != provider.calls[1][0]


def test_deadline_stops_new_calls(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("services.search_agent.core.time.monotonic", lambda: clock[0])

    class SlowProvider(Provider):
        def search(self, *args, **kwargs):
            clock[0] = 2
            return []

    result = run(SlowProvider([]), budget=SearchBudget(timeout_seconds=1))
    assert result.status == "failed" and result.stop_reason == "deadline"
    assert result.search_calls == 1


def test_planner_failure_uses_original_description():
    class BrokenPlanner:
        def next_query(self, *args):
            raise PlannerError("unavailable")

    provider = Provider([[hit("a"), hit("b"), hit("c")]])
    result = run(provider, planner=BrokenPlanner())
    assert provider.calls[0][0] == "熊猫头大笑"
    assert result.warnings == ["planner_unavailable_using_original_description"]


def test_web_mode_preserves_page_only_results():
    page = hit()
    page["image_url"] = None
    result = search_web(
        description="test",
        provider=Provider([[page]]),
        settings=settings(search_agent_mode="web"),
        budget=SearchBudget(max_rounds=1),
    )
    assert result.result_kind == "sources" and result.sources[0].image_url is None


@pytest.mark.parametrize("description", ["", " " * 5, "x" * 501])
def test_invalid_description(description):
    with pytest.raises(ValueError):
        search_web(description=description)


def test_planner_sends_only_counts_not_page_instructions():
    captured = []

    def response(request):
        captured.append(request.content.decode())
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"search","query":"熊猫头 laughing gif"}',
                        }
                    }
                ]
            },
        )

    config = SearchAgentSettings(_env_file=None, deepseek_api_key="test-secret")
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        planner = QueryPlanner(config, client)
        query = planner.next_query("熊猫头", 2, {"valid_candidates": 0}, ["熊猫头"], 1)
    assert query == "熊猫头 laughing gif" and planner.model_calls == 1
    assert "test-secret" not in captured[0]


def test_bad_planner_response_does_not_expose_body():
    config = SearchAgentSettings(_env_file=None, deepseek_api_key="test-secret")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, text="secret internal error"),
        )
    ) as client:
        with pytest.raises(PlannerError) as exc:
            QueryPlanner(config, client).next_query("a", 1, {}, [], 1)
    assert "secret" not in str(exc.value)
