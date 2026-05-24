// Tiny fetch wrapper that understands the /api {data, error} envelope.
//
// All /api/* responses come back as
//   { data: <result>, error: null }
// or
//   { data: null, error: { code, message } }
//
// apiFetch resolves with `data` on success and throws an ApiError on
// failure so callers can branch with a normal try/catch.

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message || code || "request failed");
    this.code = code || "unknown";
    this.status = status;
  }
}

export async function apiFetch(path, { method = "GET", body, headers = {} } = {}) {
  const init = { method, headers: { ...headers } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = typeof body === "string" ? body : JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(path, init);
  } catch (networkErr) {
    throw new ApiError("network_error", networkErr.message, 0);
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("invalid_response", `non-JSON response (${response.status})`, response.status);
  }

  if (!response.ok || (payload && payload.error)) {
    const err = (payload && payload.error) || { code: `http_${response.status}`, message: response.statusText };
    throw new ApiError(err.code, err.message, response.status);
  }
  return payload.data;
}
