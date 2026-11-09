"""Contract tests use no real API keys or external requests."""

import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from services.search_agent.providers import (
    MAX_RESPONSE_BYTES,
    BraveProvider,
    DDGSProvider,
    DeepSeekProvider,
    ProviderError,
    SearxngProvider,
    TavilyProvider,
)


def client_for(payload, status=200, capture=None, headers=None):
    def handle(request):
        if capture is not None:
            capture.append(request)
        return httpx.Response(status, json=payload, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_deepseek_official_schema_and_normalized_web_results():
    requests = []
    with client_for(
        {
            "results": [
                {
                    "title": "Page",
                    "url": "https://site.example/gif",
                    "snippet": "short text",
                    "summary": "long text",
                    "content": "",
                    "rerank_score": 2.4,
                }
            ]
        },
        capture=requests,
    ) as client:
        hits = DeepSeekProvider("test-secret", client=client).search("熊猫头 GIF", 50, 3)
    assert hits == [
        {
            "title": "Page",
            "source_url": "https://site.example/gif",
            "image_url": None,
            "snippet": "short text",
            "provider": "deepseek",
        }
    ]
    request = requests[0]
    assert str(request.url) == "https://api.deepseek.com/v1/tools/search"
    assert request.headers["authorization"] == "Bearer test-secret"
    assert json.loads(request.content) == {
        "query": "熊猫头 GIF",
        "count": 50,
        "need_content": False,
    }


def test_deepseek_unicode_query_limit_and_unsupported_images():
    with client_for({"results": []}) as client:
        provider = DeepSeekProvider("test-secret", client=client)
        assert provider.search("图" * 128, 1, 3) == []
        with pytest.raises(ProviderError) as exc:
            provider.search("图" * 129, 1, 3)
        assert exc.value.code == "provider_invalid_request"
        with pytest.raises(ProviderError) as exc:
            DeepSeekProvider("test-secret", "images", client=client)
        assert exc.value.code == "provider_config"


def test_deepseek_insufficient_balance_is_safe_configuration_error():
    with client_for(
        {"error": {"message": "test-secret upstream account details"}},
        status=402,
    ) as client:
        with pytest.raises(ProviderError, match="balance") as exc:
            DeepSeekProvider("test-secret", client=client).search("reaction", 1, 3)
    assert exc.value.code == "provider_config"
    assert "test-secret" not in str(exc.value)
    assert "account details" not in str(exc.value)


def test_deepseek_missing_key_and_malformed_response():
    with client_for({"not_results": []}) as client:
        with pytest.raises(ProviderError) as exc:
            DeepSeekProvider("", client=client).search("reaction", 1, 3)
        assert exc.value.code == "provider_config"
        with pytest.raises(ProviderError) as exc:
            DeepSeekProvider("test-secret", client=client).search("reaction", 1, 3)
        assert exc.value.code == "provider_invalid_response"


@pytest.mark.parametrize("mode", ["web", "images"])
def test_brave_endpoint_and_original_media(mode):
    requests = []
    item = {
        "title": "Reaction",
        "url": "https://site.example/page",
        "description": "snippet",
        "properties": {"url": "https://cdn.example/original.gif"},
        "thumbnail": {"src": "https://cdn.example/thumbnail.jpg"},
    }
    payload = {"results": [item]} if mode == "images" else {"web": {"results": [item]}}
    with client_for(payload, capture=requests) as client:
        provider = BraveProvider("test-secret", mode, client=client)
        hit = provider.search("reaction gif", 3, 4.5)[0]
        assert hit["provider"] == "brave"
        assert hit["source_url"] == item["url"]
        assert hit["image_url"] == (item["properties"]["url"] if mode == "images" else None)
        assert requests[0].url.path == f"/res/v1/{mode}/search"
        assert requests[0].headers["x-subscription-token"] == "test-secret"
        assert requests[0].url.params["count"] == "3"
        assert requests[0].extensions["timeout"]["read"] == 4.5
        provider.close()
        assert not client.is_closed


def test_tavily_keyless_images_keep_source_association_and_deduplicate():
    requests = []
    with client_for(
        {
            "results": [
                {
                    "title": "Source",
                    "url": "https://site.example/page",
                    "content": "text",
                    "images": ["https://cdn.example/a.gif"],
                }
            ],
            "images": [
                {"url": "https://cdn.example/a.gif", "description": "same"},
                {"url": "https://cdn.example/b.gif", "description": "unattributed media"},
            ],
        },
        capture=requests,
    ) as client:
        hits = TavilyProvider(mode="images", client=client).search("reaction", 3, 3)
    assert len(hits) == 2
    assert hits[0]["source_url"] == "https://site.example/page"
    assert hits[0]["image_url"] == "https://cdn.example/a.gif"
    assert hits[1]["source_url"] == "https://cdn.example/b.gif"
    request = requests[0]
    assert request.headers["x-tavily-access-mode"] == "keyless"
    assert "authorization" not in request.headers
    body = json.loads(request.content)
    assert body["include_images"] and body["include_image_descriptions"]
    assert not body["include_answer"] and not body["include_raw_content"]


def test_tavily_key_auth_and_web_result():
    requests = []
    with client_for(
        {"results": [{"title": "Page", "url": "https://site.example/", "content": "body"}]},
        capture=requests,
    ) as client:
        hits = TavilyProvider("test-secret", "web", client=client).search("reaction", 1, 3)
    assert hits[0]["image_url"] is None
    assert hits[0]["snippet"] == "body"
    assert requests[0].headers["authorization"] == "Bearer test-secret"
    assert "x-tavily-access-mode" not in requests[0].headers


@pytest.mark.parametrize("status", [200, 429])
def test_tavily_limit_envelope_is_safe(status):
    with client_for(
        {"error": {"code": "daily_cap_reached", "message": "test-secret upstream body"}},
        status=status,
    ) as client:
        with pytest.raises(ProviderError) as exc:
            TavilyProvider(client=client).search("reaction", 1, 3)
    assert exc.value.code == "provider_rate_limited"
    assert "test-secret" not in str(exc.value)
    assert "upstream body" not in str(exc.value)


def test_searxng_uses_json_category_and_img_src():
    requests = []
    with client_for(
        {
            "results": [
                {
                    "title": "GIF",
                    "url": "https://site.example/page",
                    "img_src": "https://cdn.example/a.gif",
                    "content": "description",
                }
            ]
        },
        capture=requests,
    ) as client:
        hits = SearxngProvider("http://localhost:8080/", "images", client=client).search(
            "reaction", 2, 3
        )
    assert hits[0]["image_url"] == "https://cdn.example/a.gif"
    assert requests[0].url.params["categories"] == "images"
    assert requests[0].url.params["format"] == "json"


def test_searxng_disabled_json_has_configuration_error():
    with client_for({}, status=403) as client:
        with pytest.raises(ProviderError, match="enable JSON") as exc:
            SearxngProvider("http://localhost:8080", client=client).search("reaction", 1, 3)
    assert exc.value.code == "provider_config"


@pytest.mark.parametrize("status,code", [(401, "provider_auth"), (503, "provider_unavailable")])
def test_http_status_errors_never_expose_upstream_body(status, code):
    with client_for({"secret": "test-secret"}, status=status) as client:
        with pytest.raises(ProviderError) as exc:
            BraveProvider("test-secret", client=client).search("reaction", 1, 3)
    assert exc.value.code == code
    assert "test-secret" not in str(exc.value)


def test_redirect_is_not_followed_even_if_client_default_enables_it():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://private.example/?key=secret"})

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(ProviderError) as exc:
            BraveProvider("test", client=client).search("reaction", 1, 3)
    assert exc.value.code == "provider_redirect"
    assert len(requests) == 1


@pytest.mark.parametrize("declared_length", [False, True])
def test_response_size_is_bounded(declared_length):
    def handler(request):
        headers = {"content-length": str(MAX_RESPONSE_BYTES + 1)} if declared_length else {}
        return httpx.Response(200, content=b" " * (MAX_RESPONSE_BYTES + 1), headers=headers)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as exc:
            TavilyProvider(client=client).search("reaction", 1, 3)
    assert exc.value.code == "provider_response_too_large"


def test_timeout_is_safe_and_does_not_expose_exception_url():
    def handler(request):
        raise httpx.ReadTimeout("test-secret private upstream details", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as exc:
            TavilyProvider(client=client).search("reaction", 1, 0.5)
    assert exc.value.code == "provider_timeout"
    assert "test-secret" not in str(exc.value)


def test_malformed_results_and_unusable_urls_are_not_returned():
    with client_for({"results": "invalid"}) as client:
        with pytest.raises(ProviderError) as exc:
            TavilyProvider(client=client).search("reaction", 1, 3)
    assert exc.value.code == "provider_invalid_response"
    with client_for(
        {
            "results": [
                {"title": "bad", "url": "javascript:alert(1)"},
                {"title": "bad", "url": "https://user:password@site.example/"},
                {"title": "ok", "url": "https://site.example/"},
            ]
        }
    ) as client:
        hits = TavilyProvider(client=client).search("reaction", 3, 3)
    assert [hit["title"] for hit in hits] == ["ok"]


@pytest.mark.parametrize("mode", ["web", "images"])
def test_ddgs_lazy_backend_mapping_and_normalization(monkeypatch, mode):
    calls = []

    class FakeDDGS:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def text(self, query, **kwargs):
            calls.append((query, kwargs))
            return [{"title": "Page", "href": "https://site.example/", "body": "snippet"}]

        def images(self, query, **kwargs):
            calls.append((query, kwargs))
            return [
                {
                    "title": "Image",
                    "url": "https://site.example/",
                    "image": "https://cdn.example/a.gif",
                }
            ]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))
    hits = DDGSProvider(mode).search("reaction", 2, 3)
    assert calls[0] == {"timeout": 3.0}
    assert calls[1][1]["backend"] == ("duckduckgo" if mode == "images" else "bing")
    assert hits[0]["source_url"] == "https://site.example/"
    assert hits[0]["image_url"] == ("https://cdn.example/a.gif" if mode == "images" else None)


def test_invalid_budget_and_client_ownership():
    provider = TavilyProvider()
    with pytest.raises(ProviderError) as exc:
        provider.search("reaction", 2, float("nan"))
    assert exc.value.code == "provider_invalid_request"
    provider.close()
    assert provider._client.is_closed


@pytest.mark.parametrize(
    "exception_name,code",
    [("TimeoutException", "provider_timeout"), ("RatelimitException", "provider_rate_limited")],
)
def test_ddgs_errors_are_safe(monkeypatch, exception_name, code):
    error_type = type(exception_name, (Exception,), {})

    class FailingDDGS:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def text(self, *args, **kwargs):
            raise error_type("test-secret upstream details")

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FailingDDGS))
    with pytest.raises(ProviderError) as exc:
        DDGSProvider().search("reaction", 2, 3)
    assert exc.value.code == code
    assert "test-secret" not in str(exc.value)


def test_searxng_reports_all_upstreams_unavailable():
    with client_for({"results": [], "unresponsive_engines": [["bing", "timeout"]]}) as client:
        with pytest.raises(ProviderError) as exc:
            SearxngProvider("http://localhost:8080", client=client).search("reaction", 1, 3)
    assert exc.value.code == "provider_unavailable"


@pytest.mark.parametrize("provider_name", ["tavily", "searxng", "deepseek"])
@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": {}}])
def test_required_result_list_is_not_confused_with_no_matches(provider_name, payload):
    with client_for(payload) as client:
        provider = {
            "tavily": lambda: TavilyProvider(client=client),
            "searxng": lambda: SearxngProvider("http://localhost:8080", client=client),
            "deepseek": lambda: DeepSeekProvider("test", client=client),
        }[provider_name]()
        with pytest.raises(ProviderError) as exc:
            provider.search("reaction", 2, 3)
    assert exc.value.code == "provider_invalid_response"


@pytest.mark.parametrize("provider_name", ["tavily", "searxng", "deepseek"])
def test_explicit_empty_results_remain_a_normal_no_match(provider_name):
    with client_for({"results": []}) as client:
        provider = {
            "tavily": lambda: TavilyProvider(client=client),
            "searxng": lambda: SearxngProvider("http://localhost:8080", client=client),
            "deepseek": lambda: DeepSeekProvider("test", client=client),
        }[provider_name]()
        assert provider.search("reaction", 2, 3) == []


@pytest.mark.parametrize(
    "mode,payload",
    [
        ("web", {}),
        ("web", {"web": {}}),
        ("web", {"type": "search", "query": {}}),
        ("web", {"type": "images", "query": {"original": "reaction"}}),
        ("images", {}),
        ("images", {"type": "images", "query": {"original": "reaction"}}),
    ],
)
def test_brave_unknown_or_incomplete_response_is_not_no_match(mode, payload):
    with client_for(payload) as client:
        with pytest.raises(ProviderError) as exc:
            BraveProvider("test", mode, client=client).search("reaction", 2, 3)
    assert exc.value.code == "provider_invalid_response"


@pytest.mark.parametrize(
    "mode,payload",
    [
        ("web", {"web": {"results": []}}),
        ("web", {"type": "search", "query": {"original": "reaction"}}),
        ("web", {"type": "search", "query": {"original": "reaction"}, "web": None}),
        ("images", {"results": []}),
    ],
)
def test_brave_valid_empty_responses_remain_no_match(mode, payload):
    with client_for(payload) as client:
        assert BraveProvider("test", mode, client=client).search("reaction", 2, 3) == []


@pytest.mark.parametrize("mode", ["web", "images"])
def test_brave_error_envelope_is_not_no_match(mode):
    with client_for({"type": "ErrorResponse", "error": {"message": "test-secret"}}) as client:
        with pytest.raises(ProviderError) as exc:
            BraveProvider("test", mode, client=client).search("reaction", 2, 3)
    assert exc.value.code == "provider_unavailable"
    assert "test-secret" not in str(exc.value)
