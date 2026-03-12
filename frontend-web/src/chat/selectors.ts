import type { Ask, CachedChoice } from "./types";

export function cleanPrompt(s: string): string {
  const t = String(s || "").trim();
  if (!t) return "";
  const lines = t
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter(Boolean);
  // Drop leading reset/status lines from prompts (e.g., "Reset ✅")
  while (lines.length && /^reset\b/i.test(lines[0])) lines.shift();
  return lines.join(" ");
}

export function computeAskSig(a: any): string {
  if (!a) return "";
  const type = String(a?.type || "");
  const field = String(a?.field || "");
  const prompt = String(a?.prompt || "");
  const options = Array.isArray(a?.options)
    ? a.options
        .map((o: any) =>
          typeof o === "string" ? o : String(o?.label || o?.value || "")
        )
        .slice(0, 50)
    : [];
  return JSON.stringify({ type, field, prompt, options });
}

export function willRenderAskCard(ask: Ask | null): boolean {
  const aType = String(ask?.type || "");
  const aField = String(ask?.field || "");
  const opts = Array.isArray((ask as any)?.options) ? (ask as any).options : [];
  return (
    aField === "passenger_details" ||
    aField === "departure_date" ||
    aField === "date" ||
    aField === "from" ||
    aField === "to" ||
    aField === "pax" ||
    aType === "seatmap" ||
    (aType === "choice" && Array.isArray(opts) && opts.length > 0)
  );
}

export function applyChoiceCacheFallback(args: {
  nextAsk: any;
  sayText: string;
  cachedChoice: CachedChoice;
}): any {
  const { nextAsk, sayText, cachedChoice } = args;
  const sayLower = String(sayText || "").trim().toLowerCase();

  // Server sometimes returns SAY-only for invalid choice; keep the last menu visible.
  if (!nextAsk && sayLower.includes("choose") && cachedChoice.options.length > 0) {
    return {
      type: "choice",
      field: "choice",
      prompt: cachedChoice.prompt || "Choose from above",
      options: cachedChoice.options,
    };
  }

  if (nextAsk && String(nextAsk.type || "") === "choice") {
    const opts = Array.isArray(nextAsk.options) ? nextAsk.options : [];
    if (opts.length === 0 && cachedChoice.options.length > 0) {
      nextAsk.options = cachedChoice.options;
      if (!nextAsk.prompt && cachedChoice.prompt) nextAsk.prompt = cachedChoice.prompt;
    }
  }
  return nextAsk;
}
