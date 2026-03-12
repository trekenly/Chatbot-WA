/**
 * lib/types.ts — thin re-exports from chat/types (single source of truth).
 *
 * `ChatMsg` was the old name for what is now `Bubble` in chat/types.
 * All new code should import directly from "../chat/types".
 */
export type { Role, AskOption, Ask, ChatEnv } from "../chat/types";
export type { Bubble as ChatMsg } from "../chat/types";
