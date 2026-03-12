import type { ChatEnv } from "./types";
import { postChatWithReholdRetry } from "./api";

export async function sendText(args: {
  endpoint: string;
  userId: string;
  text: string;
  state: Record<string, unknown>;
}): Promise<ChatEnv> {
  return await postChatWithReholdRetry(args);
}
