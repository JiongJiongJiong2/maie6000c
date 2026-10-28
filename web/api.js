export class ApiError extends Error {
  constructor(message, status = 0, code = "network_error") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function sameOriginPath(path) {
  const url = new URL(path, location.origin);
  if (url.origin !== location.origin || url.username || url.password) {
    throw new ApiError(
      "The server returned an unsupported media URL.",
      0,
      "invalid_media_url",
    );
  }
  return url.pathname + url.search;
}

export class Api {
  token = "";

  async request(
    path,
    { signal, timeout = 30000, media = false, binary = false, ...options } = {},
  ) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(abort, timeout);
    try {
      const headers = new Headers(options.headers);
      if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
      const response = await fetch(sameOriginPath(path), {
        ...options,
        headers,
        signal: controller.signal,
        cache: "no-store",
        redirect: "error",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const detail = body?.detail ?? body?.error;
        const message = typeof detail === "string" ? detail : detail?.message;
        const fallback = {
          401: "The access token is missing or invalid. Open Connection settings.",
          404: "Endpoint or record not found. Check that the W07 backend is connected.",
          409: "The request conflicts with an earlier submission. Start a new search.",
          410: "This GIF has expired. Start a new search.",
          413: "The image exceeds the server limit. Choose a smaller image.",
          422: "Invalid image or request. Use a cropped PNG, JPG, or WebP screenshot.",
        };
        throw new ApiError(
          fallback[response.status] ||
            message ||
            `The service is temporarily unavailable (${response.status}).`,
          response.status,
          detail?.code || "http_error",
        );
      }
      if (media) {
        const blob = await response.blob();
        const signature = new TextDecoder().decode(
          await blob.slice(0, 6).arrayBuffer(),
        );
        if (
          blob.type.split(";")[0] !== "image/gif" ||
          !["GIF87a", "GIF89a"].includes(signature)
        ) {
          throw new ApiError(
            "The returned file is not a valid GIF.",
            0,
            "invalid_media",
          );
        }
        return blob;
      }
      if (binary) return await response.blob();
      return await response.json();
    } catch (error) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      if (error instanceof ApiError) throw error;
      throw new ApiError(
        "Connection interrupted or timed out. Check the service and try again.",
        0,
        "network_error",
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }

  submit(file, key, signal) {
    const body = new FormData();
    body.set("image", file, file.name);
    body.set("client_submission_key", key);
    return this.request("/search-requests", { method: "POST", body, signal });
  }

  status(id, signal) {
    return this.request(`/search-requests/${encodeURIComponent(id)}`, {
      signal,
    });
  }

  review(jobId, payload, signal) {
    return this.request(`/search-jobs/${encodeURIComponent(jobId)}/reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  }

  media(url, signal) {
    return this.request(url, { signal, media: true, timeout: 60000 });
  }
}

const uuidPattern = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
export function validAccepted(data) {
  if (
    !uuidPattern.test(data?.request_id) ||
    !uuidPattern.test(data?.job_id) ||
    !["pending", "running", "completed", "failed"].includes(data?.status)
  ) {
    throw new ApiError(
      "The server response does not match the W07 API contract.",
      0,
      "invalid_response",
    );
  }
  return data;
}

export function validStatus(data) {
  validAccepted(data);
  if (
    !Array.isArray(data.candidates) ||
    data.candidates.length > 3 ||
    (data.status === "completed" &&
      !["candidates", "no_candidates"].includes(data.result_kind)) ||
    (data.status !== "completed" && data.result_kind !== null) ||
    (data.status === "failed" &&
      (typeof data.error?.code !== "string" ||
        typeof data.error?.message !== "string")) ||
    (data.status !== "completed" && data.candidates.length) ||
    (data.result_kind === "no_candidates" && data.candidates.length) ||
    (data.result_kind === "candidates" && !data.candidates.length)
  ) {
    throw new ApiError(
      "The search status does not match the W07 API contract.",
      0,
      "invalid_response",
    );
  }
  const ids = new Set();
  const ranks = new Set();
  for (const candidate of data.candidates) {
    if (
      !uuidPattern.test(candidate.candidate_id) ||
      !Number.isFinite(candidate.score) ||
      !Number.isInteger(candidate.rank) ||
      candidate.rank < 1 ||
      candidate.rank > 3 ||
      typeof candidate.media_url !== "string" ||
      ids.has(candidate.candidate_id) ||
      ranks.has(candidate.rank)
    ) {
      throw new ApiError(
        "Candidate data is incomplete. Check the backend integration.",
        0,
        "invalid_response",
      );
    }
    sameOriginPath(candidate.media_url);
    ids.add(candidate.candidate_id);
    ranks.add(candidate.rank);
  }
  return data;
}
