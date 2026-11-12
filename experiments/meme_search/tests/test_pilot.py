import importlib.util
import hashlib
import io
from pathlib import Path
import socket

import httpx
from PIL import Image
import pytest

SPEC = importlib.util.spec_from_file_location("pilot", Path(__file__).parents[1] / "pilot.py")
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)
REUSE_SPEC = importlib.util.spec_from_file_location(
    "reuse_smoke", Path(__file__).parents[1] / "reuse_smoke.py"
)
reuse = importlib.util.module_from_spec(REUSE_SPEC)
REUSE_SPEC.loader.exec_module(reuse)


def run_case(case_id="one"):
    return {
        "id": case_id,
        "category": "blank",
        "input": "test",
        "arms": {
            arm: {
                "query": "test",
                "elapsed_seconds": 1,
                "results": [
                    {"rank": rank, "title": "x", "url": "https://example.com"} for rank in (1, 5, 6)
                ],
            }
            for arm in pilot.ARMS
        },
    }


def runs(*cases):
    return {"protocol_version": 1, "provider": "host_web_search", "cases": list(cases)}


def judgment(case_id="one", arm="literal", relevant=None, blank=None, gif=None):
    return {
        "case_id": case_id,
        "arm": arm,
        "relevant_ranks": relevant,
        "blank_ranks": blank,
        "gif_ranks": gif,
    }


def test_known_denominator_and_cutoff():
    result = pilot.summarize(
        runs(run_case(), run_case("two"), run_case("three")),
        {"items": [judgment(relevant=[6], blank=[5]), judgment("two", relevant=[])]},
    )
    literal = result["by_arm"]["literal"]
    assert literal["counted_cases"] == 3
    assert literal["missing_judgments"] == 1
    assert literal["top5_page_discovery"] == {
        "successes": 0,
        "judged_cases": 2,
        "unknown_cases": 1,
        "rate": 0,
    }
    assert literal["top5_blank_page_discovery"]["rate"] == 1
    assert literal["top5_gif_page_discovery"]["rate"] is None
    assert literal["mean_reciprocal_rank"]["value"] == 0
    assert result["by_arm"]["skill"]["top5_page_discovery"]["rate"] is None


def test_mrr_at5_boundary_and_unknown_denominator():
    result = pilot.summarize(
        runs(run_case(), run_case("two"), run_case("unknown")),
        {"items": [judgment(relevant=[5, 6]), judgment("two", relevant=[6])]},
    )
    assert result["by_arm"]["literal"]["mean_reciprocal_rank"] == {
        "value": pytest.approx(0.1),
        "judged_cases": 2,
        "cutoff": 5,
    }


def test_empty_results_cannot_succeed():
    case = run_case()
    case["arms"]["literal"]["results"] = []
    result = pilot.summarize(runs(case), {"items": [judgment(relevant=[])]})
    assert result["by_arm"]["literal"]["top5_page_discovery"]["rate"] == 0
    with pytest.raises(ValueError):
        pilot.summarize(runs(case), {"items": [judgment(relevant=[1])]})


@pytest.mark.parametrize("ranks", [[0], [2], [-1], [True], [1, 1], "1"])
def test_invalid_judgment_ranks(ranks):
    with pytest.raises(ValueError):
        pilot.summarize(runs(run_case()), {"items": [judgment(relevant=ranks)]})


def test_reject_duplicates_and_wrong_arm():
    with pytest.raises(ValueError):
        pilot.summarize(runs(run_case(), run_case()), {})
    with pytest.raises(ValueError):
        pilot.summarize(runs(run_case()), {"items": [judgment(), judgment()]})
    with pytest.raises(ValueError):
        pilot.summarize(runs(run_case()), {"items": [judgment(arm="typo")]})
    case = run_case()
    case["arms"]["other"] = case["arms"].pop("skill")
    with pytest.raises(ValueError):
        pilot.summarize(runs(case), {})


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "224.0.0.1"]
)
def test_private_dns_blocked(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    with pytest.raises(pilot.ProbeFailure):
        pilot.validate_public_url("https://public.example/")


def public_dns(monkeypatch):
    def resolve(host, *a, **kw):
        address = "127.0.0.1" if host == "localhost" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


def test_redirect_private_blocked_and_secret_sanitized(monkeypatch, tmp_path):
    public_dns(monkeypatch)
    requested = []

    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://localhost/secret?token=hidden"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = pilot.probe_one({"id": "a", "url": "https://public.example/"}, tmp_path, client)
    assert result["error"] == "non_public_address"
    assert len(requested) == 1
    assert "hidden" not in str(result)
    assert not list(tmp_path.iterdir())


def test_nonimage_rejected(monkeypatch, tmp_path):
    public_dns(monkeypatch)
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="html"))
    ) as client:
        result = pilot.probe_one({"id": "a", "url": "https://public.example/"}, tmp_path, client)
    assert result["error"] == "unsupported_mime"


def test_valid_image_and_mime_mismatch(monkeypatch, tmp_path):
    public_dns(monkeypatch)
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6)).save(buffer, format="PNG")
    data = buffer.getvalue()
    for mime, expected in [("image/png", "verified_image"), ("image/gif", "failed")]:
        with httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=data, headers={"content-type": mime})
            )
        ) as client:
            result = pilot.probe_one(
                {"id": "a", "url": "https://public.example/"}, tmp_path, client
            )
        assert result["status"] == expected
        if expected == "verified_image":
            assert (result["width"], result["height"], result["frame_count"]) == (8, 6, 1)
            assert (tmp_path / result["sha256"]).read_bytes() == data


def test_cache_cannot_escape():
    with pytest.raises(ValueError):
        pilot.probe({"items": []}, Path("outside-cache"))


@pytest.mark.parametrize("cap_name,cap", [("MAX_FRAMES", 2), ("MAX_TOTAL_PIXELS", 10)])
def test_animation_limits_before_caching(monkeypatch, tmp_path, cap_name, cap):
    public_dns(monkeypatch)
    monkeypatch.setattr(pilot, cap_name, cap)
    buffer = io.BytesIO()
    frames = [Image.new("RGB", (2, 2), color) for color in ("red", "blue", "green")]
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, content=buffer.getvalue(), headers={"content-type": "image/gif"}
            )
        )
    ) as client:
        result = pilot.probe_one(
            {"id": "animation", "url": "https://public.example/a.gif"}, tmp_path, client
        )
    assert result["error"] == "decoded_size_limit"
    assert not list(tmp_path.iterdir())


def test_cache_existing_symlink_never_overwrites(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    victim = tmp_path / "outside.txt"
    victim.write_bytes(b"untouched")
    data = b"downloaded image bytes"
    digest = hashlib.sha256(data).hexdigest()
    target = cache / digest
    try:
        target.symlink_to(victim)
    except OSError:
        # Windows accounts without symlink privilege still exercise the reject
        # branch against an existing entry, and assert it cannot be overwritten.
        target.write_bytes(b"untouched")
        real_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path, "is_symlink", lambda path: path == target or real_is_symlink(path)
        )
    with pytest.raises(pilot.ProbeFailure, match="unsafe_cache_entry"):
        pilot.cache_image(cache, digest, data)
    assert victim.read_bytes() == b"untouched"
    assert target.read_bytes() == b"untouched"


def test_cache_existing_regular_requires_matching_checksum(tmp_path):
    data = b"verified bytes"
    digest = hashlib.sha256(data).hexdigest()
    target = tmp_path / digest
    target.write_bytes(b"corrupt existing bytes")
    with pytest.raises(pilot.ProbeFailure, match="cache_checksum_mismatch"):
        pilot.cache_image(tmp_path, digest, data)
    assert target.read_bytes() == b"corrupt existing bytes"
    target.write_bytes(data)
    pilot.cache_image(tmp_path, digest, data)
    assert target.read_bytes() == data


@pytest.mark.parametrize("stored", [{"current", "stale"}, set(), {"unrelated"}])
def test_query_corpus_rejects_stale_or_missing_shas(stored):
    with pytest.raises(reuse.CorpusMismatch):
        reuse.validate_query_corpus(stored, [{"sha256": "current"}])


def test_query_corpus_exact_match_uses_sha_not_ids():
    reuse.validate_query_corpus({"current"}, [{"sha256": "current", "id": "different label"}])
