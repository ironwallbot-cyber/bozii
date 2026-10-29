/** Typed fetch wrapper for the Bozii API (same-origin, cookie auth). */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { body, headers, ...rest } = options;
  const response = await fetch(path, {
    credentials: "include",
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(headers ?? {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    ...rest,
  });

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const record = (payload ?? {}) as { error?: string; code?: string; detail?: unknown };
    throw new ApiError(
      response.status,
      record.code ?? "error",
      record.error ?? `Request failed (${response.status})`,
      record.detail,
    );
  }
  return payload as T;
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: "POST", body });
export const patch = <T>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });

/** Human readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (Array.isArray(error.detail) && error.detail.length) {
      const parts = error.detail.map((item) => {
        if (item && typeof item === "object" && "message" in item) {
          const field = (item as { field?: string }).field;
          return `${field ? `${field}: ` : ""}${(item as { message: string }).message}`;
        }
        return String(item);
      });
      return `${error.message} — ${parts.join("; ")}`;
    }
    if (typeof error.detail === "string") return `${error.message} — ${error.detail}`;
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return String(error);
}
