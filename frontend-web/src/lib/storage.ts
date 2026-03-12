export function safeGetStorage(key: string): string {
  try {
    return String(localStorage.getItem(key) || "");
  } catch {
    return "";
  }
}

export function safeSetStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, String(value || ""));
  } catch {
    // ignore storage failures in private browsing / locked-down webviews
  }
}

export function readJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJSON(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // ignore storage failures in private browsing / locked-down webviews
  }
}
