import type { TokenPair } from "./types";

const TOKEN_STORAGE_KEY = "orderflow.session.v1";

interface ErrorEnvelope {
  error?: { code?: string; message?: string };
  detail?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }
}

function isTokenPair(value: unknown): value is TokenPair {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<TokenPair>;
  return (
    typeof candidate.access_token === "string" &&
    typeof candidate.refresh_token === "string" &&
    typeof candidate.expires_in === "number"
  );
}

export function loadTokens(): TokenPair | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isTokenPair(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveTokens(tokens: TokenPair): void {
  window.sessionStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(tokens));
}

export function clearTokens(): void {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}

let refreshPromise: Promise<TokenPair | null> | null = null;

async function refreshTokens(): Promise<TokenPair | null> {
  const current = loadTokens();
  if (!current) return null;
  const response = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: current.refresh_token }),
  });
  if (!response.ok) {
    clearTokens();
    return null;
  }
  const tokens = (await response.json()) as TokenPair;
  saveTokens(tokens);
  return tokens;
}

async function parseError(response: Response): Promise<ApiError> {
  let payload: ErrorEnvelope = {};
  try {
    payload = (await response.json()) as ErrorEnvelope;
  } catch {
    // The stable fallback below handles non-JSON upstream failures.
  }
  return new ApiError(
    payload.error?.message ?? payload.detail ?? "Не удалось выполнить запрос",
    response.status,
    payload.error?.code ?? "request_failed",
  );
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: { auth?: boolean; retry?: boolean } = {},
): Promise<T> {
  const auth = options.auth ?? true;
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const tokens = auth ? loadTokens() : null;
  if (tokens) headers.set("Authorization", `Bearer ${tokens.access_token}`);

  const response = await fetch(`/api/v1${path}`, { ...init, headers, cache: "no-store" });
  if (response.status === 401 && auth && options.retry !== false && tokens) {
    refreshPromise ??= refreshTokens().finally(() => {
      refreshPromise = null;
    });
    if (await refreshPromise) return apiRequest<T>(path, init, { auth, retry: false });
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
