"""Small search adapters; HTTP clients supplied by callers remain caller-owned.

Adapters only discover URLs. They do not fetch search-result pages or media.
The worker supplies the hard execution deadline; HTTP reads also enforce a
cooperative per-call deadline and a decompressed response-size limit.
"""

from __future__ import annotations

import json
import math
import time
from typing import Literal
from urllib.parse import urlsplit

import httpx

SearchMode = Literal["web", "images"]
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ProviderError(RuntimeError):
    """A stable code and safe message, without upstream bodies or credentials."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _mode(value: str) -> SearchMode:
    if value not in {"web", "images"}:
        raise ProviderError("provider_config", "Search mode must be web or images.")
    return value


def _arguments(
    query: str, limit: int, timeout: float, *, max_chars=400, max_words=50, max_results=20
) -> tuple[str, int, float]:
    if not isinstance(query, str) or not query.strip():
        raise ProviderError("provider_invalid_request", "A search query is required.")
    query = query.strip()
    if len(query) > max_chars or (max_words is not None and len(query.split()) > max_words):
        raise ProviderError("provider_invalid_request", "The search query is too long.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= max_results:
        raise ProviderError(
            "provider_invalid_request", f"Result limit must be between 1 and {max_results}."
        )
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ProviderError("provider_invalid_request", "A positive timeout is required.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ProviderError("provider_invalid_request", "A positive timeout is required.")
    return query, limit, float(timeout)


def _url(value) -> str | None:
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        parsed.port
    except ValueError:
        return None
    return value


def _text(value, cap=2000) -> str:
    return value[:cap] if isinstance(value, str) else ""


def _hit(provider, title, source_url, image_url=None, snippet="") -> dict | None:
    source_url = _url(source_url)
    if source_url is None:
        return None
    return {
        "title": _text(title, 300),
        "source_url": source_url,
        "image_url": _url(image_url),
        "snippet": _text(snippet),
        "provider": provider,
    }


def _items(value) -> list:
    if not isinstance(value, list):
        raise ProviderError("provider_invalid_response", "Search returned an invalid result list.")
    return value


class _HTTPProvider:
    def __init__(self, mode: SearchMode, client: httpx.Client | None):
        self.mode = _mode(mode)
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(follow_redirects=False)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method, url, timeout, **kwargs) -> dict:
        deadline = time.monotonic() + timeout
        try:
            with self._client.stream(
                method, url, timeout=timeout, follow_redirects=False, **kwargs
            ) as response:
                if response.status_code == 429:
                    raise ProviderError(
                        "provider_rate_limited", "Search provider rate limit reached."
                    )
                if response.status_code in {401, 403}:
                    raise ProviderError("provider_auth", "Search provider rejected access.")
                if response.status_code == 402:
                    raise ProviderError(
                        "provider_config", "Search provider account balance is insufficient."
                    )
                if 300 <= response.status_code < 400:
                    raise ProviderError(
                        "provider_redirect", "Search provider redirects are disabled."
                    )
                if not response.is_success:
                    raise ProviderError("provider_unavailable", "Search provider request failed.")
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        oversized = int(content_length) > MAX_RESPONSE_BYTES
                    except ValueError:
                        oversized = False
                    if oversized:
                        raise ProviderError(
                            "provider_response_too_large", "Search response exceeds the size limit."
                        )
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        raise ProviderError("provider_timeout", "Search provider timed out.")
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ProviderError(
                            "provider_response_too_large", "Search response exceeds the size limit."
                        )
                    body.extend(chunk)
                if time.monotonic() >= deadline:
                    raise ProviderError("provider_timeout", "Search provider timed out.")
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ValueError()
                return result
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError("provider_timeout", "Search provider timed out.") from None
        except httpx.HTTPError:
            raise ProviderError("provider_unavailable", "Search provider request failed.") from None
        except (ValueError, UnicodeError):
            raise ProviderError(
                "provider_invalid_response", "Search returned an invalid JSON response."
            ) from None


class DeepSeekProvider(_HTTPProvider):
    """Official web Search API; this does not call Fetch or recover images."""

    name = "deepseek"

    def __init__(self, api_key: str, mode: SearchMode = "web", *, client=None):
        if mode != "web":
            raise ProviderError("provider_config", "DeepSeek Search supports web mode only.")
        self.api_key = api_key
        super().__init__(mode, client)

    def search(self, query: str, limit: int, timeout: float) -> list[dict]:
        query, limit, timeout = _arguments(
            query, limit, timeout, max_chars=128, max_words=None, max_results=50
        )
        if not self.api_key:
            raise ProviderError("provider_config", "DeepSeek Search requires an API key.")
        payload = self._request(
            "POST",
            "https://api.deepseek.com/v1/tools/search",
            timeout,
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            json={"query": query, "count": limit, "need_content": False},
        )
        if payload.get("error") is not None:
            raise ProviderError("provider_unavailable", "DeepSeek Search returned an error.")
        hits = []
        for item in _items(payload.get("results")):
            if not isinstance(item, dict):
                continue
            hit = _hit(self.name, item.get("title"), item.get("url"), snippet=item.get("snippet"))
            if hit:
                hits.append(hit)
            if len(hits) == limit:
                break
        return hits


class BraveProvider(_HTTPProvider):
    name = "brave"

    def __init__(self, api_key: str, mode: SearchMode = "web", *, client=None):
        self.api_key = api_key
        super().__init__(mode, client)

    def search(self, query: str, limit: int, timeout: float) -> list[dict]:
        query, limit, timeout = _arguments(query, limit, timeout)
        if not self.api_key:
            raise ProviderError("provider_config", "Brave requires an API key.")
        payload = self._request(
            "GET",
            f"https://api.search.brave.com/res/v1/{self.mode}/search",
            timeout,
            params={"q": query, "count": limit, "safesearch": "strict"},
            headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
        )
        if payload.get("error") is not None or payload.get("type") == "ErrorResponse":
            raise ProviderError("provider_unavailable", "Brave returned an error.")
        if self.mode == "images":
            results = _items(payload.get("results"))
        else:
            web = payload.get("web")
            if isinstance(web, dict):
                results = _items(web.get("results"))
            elif web is None:
                query_info = payload.get("query")
                if (
                    payload.get("type") != "search"
                    or not isinstance(query_info, dict)
                    or not isinstance(query_info.get("original"), str)
                    or not query_info["original"].strip()
                ):
                    raise ProviderError("provider_invalid_response", "Invalid Brave web response.")
                # The web section is optional in a valid Brave SearchResponse.
                results = []
            else:
                raise ProviderError("provider_invalid_response", "Invalid Brave web results.")
        hits = []
        for item in _items(results):
            if not isinstance(item, dict):
                continue
            properties = item.get("properties") or {}
            image_url = properties.get("url") if isinstance(properties, dict) else None
            if self.mode == "images" and _url(image_url) is None:
                continue
            hit = _hit(
                self.name,
                item.get("title"),
                item.get("url"),
                image_url if self.mode == "images" else None,
                item.get("description"),
            )
            if hit:
                hits.append(hit)
            if len(hits) == limit:
                break
        return hits


class TavilyProvider(_HTTPProvider):
    name = "tavily"

    def __init__(self, api_key: str = "", mode: SearchMode = "web", *, client=None):
        self.api_key = api_key
        super().__init__(mode, client)

    def search(self, query: str, limit: int, timeout: float) -> list[dict]:
        query, limit, timeout = _arguments(query, limit, timeout)
        headers = {"Content-Type": "application/json", "X-Client-Source": "memeretrieve"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        else:
            headers["X-Tavily-Access-Mode"] = "keyless"
        payload = self._request(
            "POST",
            "https://api.tavily.com/search",
            timeout,
            headers=headers,
            json={
                "query": query,
                "max_results": limit,
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": False,
                "include_images": self.mode == "images",
                "include_image_descriptions": self.mode == "images",
            },
        )
        if payload.get("error") is not None:
            error = payload["error"]
            code = error.get("code", "") if isinstance(error, dict) else ""
            if isinstance(code, str) and any(t in code.lower() for t in ("cap", "limit", "rate")):
                raise ProviderError("provider_rate_limited", "Tavily usage limit reached.")
            raise ProviderError("provider_unavailable", "Tavily returned an error.")
        results = _items(payload.get("results"))
        hits = []
        seen = set()

        def add_image(value, page_url=None, title="", snippet=""):
            image_url = value.get("url") if isinstance(value, dict) else value
            if _url(image_url) is None or image_url in seen:
                return
            description = value.get("description", snippet) if isinstance(value, dict) else snippet
            # Some top-level images lack a source page. Cite the actual media URL,
            # rather than inventing a source-page association.
            hit = _hit(
                self.name, title or description, page_url or image_url, image_url, description
            )
            if hit:
                seen.add(image_url)
                hits.append(hit)

        for item in results:
            if not isinstance(item, dict):
                continue
            if self.mode == "web":
                hit = _hit(
                    self.name, item.get("title"), item.get("url"), snippet=item.get("content")
                )
                if hit:
                    hits.append(hit)
            else:
                images = item.get("images", [])
                if isinstance(images, list):
                    for image in images:
                        add_image(image, item.get("url"), item.get("title"), item.get("content"))
        if self.mode == "images":
            for image in _items(payload.get("images", [])):
                add_image(image)
        return hits[:limit]


class SearxngProvider(_HTTPProvider):
    name = "searxng"

    def __init__(self, base_url: str, mode: SearchMode = "web", *, client=None):
        if _url(base_url) is None:
            raise ProviderError("provider_config", "SearXNG requires an HTTP(S) instance URL.")
        parsed = urlsplit(base_url)
        if parsed.query or parsed.fragment:
            raise ProviderError("provider_config", "SearXNG instance URL cannot contain a query.")
        self.base_url = base_url.rstrip("/")
        super().__init__(mode, client)

    def search(self, query: str, limit: int, timeout: float) -> list[dict]:
        query, limit, timeout = _arguments(query, limit, timeout)
        try:
            payload = self._request(
                "GET",
                self.base_url + "/search",
                timeout,
                params={
                    "q": query,
                    "format": "json",
                    "safesearch": 2,
                    "categories": "images" if self.mode == "images" else "general",
                },
            )
        except ProviderError as exc:
            if exc.code == "provider_auth":
                raise ProviderError(
                    "provider_config",
                    "SearXNG rejected access; enable JSON format on the instance.",
                ) from None
            raise
        hits = []
        for item in _items(payload.get("results")):
            if not isinstance(item, dict):
                continue
            image_url = item.get("img_src") if self.mode == "images" else None
            if self.mode == "images" and _url(image_url) is None:
                continue
            hit = _hit(
                self.name, item.get("title"), item.get("url"), image_url, item.get("content")
            )
            if hit:
                hits.append(hit)
            if len(hits) == limit:
                break
        if not hits and payload.get("unresponsive_engines"):
            raise ProviderError(
                "provider_unavailable", "SearXNG upstream engines were unavailable."
            )
        return hits


class DDGSProvider:
    """Optional educational metasearch adapter; DDGS owns its network clients."""

    name = "ddgs"

    def __init__(self, mode: SearchMode = "web", backend: str | None = None):
        self.mode = _mode(mode)
        self.backend = backend or ("duckduckgo" if mode == "images" else "bing")

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def search(self, query: str, limit: int, timeout: float) -> list[dict]:
        query, limit, timeout = _arguments(query, limit, timeout)
        try:
            from ddgs import DDGS
        except ImportError:
            raise ProviderError(
                "provider_missing_dependency", "Install the optional ddgs search dependency."
            ) from None
        try:
            with DDGS(timeout=timeout) as engine:
                search = engine.images if self.mode == "images" else engine.text
                results = search(query, max_results=limit, backend=self.backend, safesearch="on")
            items = _items(results)
            if len(json.dumps(items).encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ProviderError(
                    "provider_response_too_large", "Search response exceeds the size limit."
                )
        except ProviderError:
            raise
        except Exception as exc:
            if type(exc).__name__ == "TimeoutException":
                raise ProviderError("provider_timeout", "DDGS search timed out.") from None
            if type(exc).__name__ == "RatelimitException":
                raise ProviderError("provider_rate_limited", "DDGS rate limit reached.") from None
            raise ProviderError("provider_unavailable", "DDGS search is unavailable.") from None
        hits = []
        for item in items:
            if not isinstance(item, dict):
                continue
            image_url = item.get("image") if self.mode == "images" else None
            if self.mode == "images" and _url(image_url) is None:
                continue
            hit = _hit(
                self.name,
                item.get("title"),
                item.get("url") if self.mode == "images" else item.get("href"),
                image_url,
                item.get("body"),
            )
            if hit:
                hits.append(hit)
            if len(hits) == limit:
                break
        return hits
