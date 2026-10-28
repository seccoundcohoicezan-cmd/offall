export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

let refreshing: Promise<boolean> | null = null;

/** One shared refresh at a time; the refresh cookie is httpOnly so JS never sees tokens. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code: string; message: string } };
    if (body.error) return new ApiError(res.status, body.error.code, body.error.message);
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, `http_${res.status}`, res.statusText || "Permintaan gagal");
}

export async function api<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
  retry = true,
): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`/api/v1${path}`, {
    ...rest,
    credentials: "same-origin",
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 401 && retry && !path.startsWith("/auth/")) {
    if (await refreshSession()) return api<T>(path, init, false);
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, json?: unknown) => api<T>(path, { method: "POST", json: json ?? {} });
export const patch = <T>(path: string, json: unknown) => api<T>(path, { method: "PATCH", json });
export const del = (path: string) => api<void>(path, { method: "DELETE" });
