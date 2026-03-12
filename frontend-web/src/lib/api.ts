import type { ChatEnv } from "./types";

export async function postJSON<T = any>(path: string, payload: any): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  if (!res.ok) {
    let detail = "";
    try {
      const j = await res.json();
      detail = j?.error ? String(j.error) : JSON.stringify(j);
    } catch {
      detail = await res.text();
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function postChat(args: {
  endpoint: string;
  userId: string;
  text: string;
  state: Record<string, unknown>;
}): Promise<ChatEnv> {
  // Prevent infinite "typing dots" if the backend/proxy hangs.
  const controller = new AbortController();
  const timeoutMs = 60000;
  const to = window.setTimeout(() => controller.abort(), timeoutMs);

  const payload = {
    user_id: args.userId,
    text: String(args.text ?? ""),
    state: args.state ?? {},
    locale: "en_US",
    time_zone: "Asia/Bangkok",
    currency: "THB",
  };

  let res: Response;
  try {
    res = await fetch(args.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (e: any) {
    if (controller.signal.aborted) {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    throw e;
  } finally {
    window.clearTimeout(to);
  }

  if (!res.ok) {
    let detail = "";
    try {
      const j = await res.json();
      detail = j?.error ? String(j.error) : JSON.stringify(j);
    } catch {
      detail = await res.text();
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }

  return (await res.json()) as ChatEnv;
}
