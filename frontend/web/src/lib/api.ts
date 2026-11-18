import type {
  DocumentAsset,
  DocumentItem,
  Explanation,
  SearchResponse,
  SessionInfo,
  UploadResponse,
} from "./types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(
    new RegExp("(?:^|; )" + name.replace(/([.$?*|{}()[\]\\/+^])/g, "\\$1") + "=([^;]*)"),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const CSRF_STORAGE_KEY = "studbud-csrf";

function readStoredCsrf(): string | null {
  try {
    return localStorage.getItem(CSRF_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeCsrf(token: string | null): void {
  try {
    if (token) localStorage.setItem(CSRF_STORAGE_KEY, token);
    else localStorage.removeItem(CSRF_STORAGE_KEY);
  } catch {
    // Storage can be unavailable; the readable cookie is the primary source.
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);

  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (UNSAFE_METHODS.has(method)) {
    // Same-origin clients read the cookie. Cross-origin clients cannot, so
    // fall back to the token handed back in the sign-in response header.
    const csrf = readCookie("sb_csrf") ?? readStoredCsrf();
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
  });

  const issuedCsrf = response.headers.get("X-CSRF-Token");
  if (issuedCsrf) storeCsrf(issuedCsrf);

  if (!response.ok) {
    let detail = response.statusText || "Request failed.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Keep the status text.
    }
    if (response.status === 401 && !path.includes("/api/auth/sign-in")) {
      window.dispatchEvent(new Event("studbud:unauthorized"));
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiBlob(path: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("studbud:unauthorized"));
    throw new ApiError(response.status, "Asset could not be loaded.");
  }
  return response.blob();
}

export const authApi = {
  me: () => api<SessionInfo>("/api/auth/me"),
  signIn: (key: string) =>
    api<void>("/api/auth/sign-in", { method: "POST", body: JSON.stringify({ key }) }),
  signOut: async () => {
    try {
      await api<void>("/api/auth/sign-out", { method: "POST" });
    } finally {
      storeCsrf(null);
    }
  },
};

export const documentsApi = {
  list: () => api<DocumentItem[]>("/api/documents"),
  get: (id: string) => api<DocumentItem>(`/api/documents/${id}`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return api<UploadResponse>("/api/documents", { method: "POST", body: form });
  },
  remove: (id: string) => api<void>(`/api/documents/${id}`, { method: "DELETE" }),
  retry: (id: string) => api<DocumentItem>(`/api/documents/${id}/retry`, { method: "POST" }),
  assets: (id: string, page?: number) =>
    api<DocumentAsset[]>(
      `/api/documents/${id}/assets${page ? `?page=${page}` : ""}`,
    ),
  fileUrl: (id: string, page?: number) =>
    `${API_BASE}/api/documents/${id}/file${page ? `#page=${page}` : ""}`,
};

export const searchApi = {
  search: (query: string) =>
    api<SearchResponse>(`/api/search?q=${encodeURIComponent(query)}`),
};

export const explanationsApi = {
  create: (chunkId: string, question?: string) =>
    api<Explanation>("/api/explanations", {
      method: "POST",
      body: JSON.stringify({ chunk_id: chunkId, question: question || null }),
    }),
  get: (id: string) => api<Explanation>(`/api/explanations/${id}`),
};
