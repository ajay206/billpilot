import { csrfToken } from "./auth";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export type ApiResult<T> = { data: T; total: number | null };

export type Api = {
  get<T>(path: string): Promise<ApiResult<T>>;
  post<T>(path: string, body: unknown): Promise<ApiResult<T>>;
};

export function qs(path: string, params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `${path}?${text}` : path;
}

export function createApi(onUnauthorized?: () => void): Api {
  async function call<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
    const headers = new Headers(init?.headers);
    const method = (init?.method || "GET").toUpperCase();
    if (init?.body) headers.set("Content-Type", "application/json");
    if (method !== "GET" && method !== "HEAD") {
      const token = csrfToken();
      if (token) headers.set("X-CSRF-Token", token);
    }
    const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
    const totalHeader = response.headers.get("X-Total-Count");
    const total = totalHeader == null ? null : Number(totalHeader);
    if (response.status === 401 && onUnauthorized && !path.startsWith("/auth/login")) {
      onUnauthorized();
    }
    if (!response.ok) {
      let message = `Request failed (${response.status}).`;
      try {
        const body = (await response.json()) as { message?: string };
        if (body.message) message = body.message;
      } catch {
        /* The error body is not always JSON. */
      }
      throw new ApiError(response.status, message);
    }
    if (response.status === 204) return { data: undefined as T, total };
    return { data: (await response.json()) as T, total };
  }

  return {
    get: (path) => call(path),
    post: (path, body) => call(path, { method: "POST", body: JSON.stringify(body) }),
  };
}
