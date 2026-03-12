import type { ChatEnv } from "./types";
import { postChat as postChatLegacy, postJSON } from "../lib/api";

export async function postChat(args: {
  endpoint: string;
  userId: string;
  text: string;
  state: Record<string, unknown>;
}): Promise<ChatEnv> {
  // Re-export legacy API but typed to chat/types.
  return (await postChatLegacy(args)) as any;
}

/**
 * Best-effort "re-hold then retry" for intermittent GDS failures.
 *
 * If the backend doesn't expose /buyer/rehold, this will simply fall back
 * to the original error.
 */
export async function postChatWithReholdRetry(args: {
  endpoint: string;
  userId: string;
  text: string;
  state: Record<string, unknown>;
}): Promise<ChatEnv> {
  try {
    return await postChat(args);
  } catch (e: any) {
    const msg = String(e?.message || e || "");
    const looksLike1007 = msg.includes("1007") || msg.toLowerCase().includes("no data");
    if (!looksLike1007) throw e;

    // Attempt re-hold endpoint; ignore failures and rethrow original if retry fails.
    try {
      await postJSON("/buyer/rehold", { state: args.state });
    } catch {
      // no-op
    }

    // Retry once.
    return await postChat(args);
  }
}
