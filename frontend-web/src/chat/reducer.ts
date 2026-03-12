import type { Ask, ChatEnv, ChatState, PassengerSnap } from "./types";
import { applyChoiceCacheFallback, willRenderAskCard } from "./selectors";
import { parseReservationCard } from "../components/ReservationCard";

export type Action =
  | { type: "SET_DEBUG"; debug: boolean }
  | { type: "BOOT_START"; pendingAskSig: string }
  | { type: "BOOT_OK"; env: ChatEnv; cachedChoice: ChatState["cachedChoice"]; lastPassenger: PassengerSnap | null }
  | { type: "BOOT_FAIL"; errorText: string }
  | { type: "SEND_START"; pendingAskSig: string; echoUserText?: string }
  | { type: "SEND_OK"; env: ChatEnv; userText?: string; cachedChoice: ChatState["cachedChoice"] }
  | { type: "SEND_FAIL"; errorText: string; userText?: string }
  | { type: "SET_LAST_PASSENGER"; passenger: PassengerSnap | null }
  | { type: "SET_RESERVATION"; reservation: any | null };

const uid = () => crypto.randomUUID();

function lastBotText(msgs: ChatState["bubbles"]): string {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i]?.role === "bot") return String(msgs[i]?.text || "");
  }
  return "";
}

function maybeSetReservation(state: ChatState, botText: string): ChatState {
  const parsed = parseReservationCard(String(botText || "").trim());
  if (!parsed) return state;
  const passenger = state.lastPassenger || undefined;
  return {
    ...state,
    reservation: { ...(parsed as any), passenger },
  };
}

function normalizeEnvAsk(env: ChatEnv, cachedChoice: ChatState["cachedChoice"]): Ask | null {
  const sayText = String(env.say || "").trim();
  const rawAsk: any = (env.ask || null) as any;
  let nextAsk: any = rawAsk;
  nextAsk = applyChoiceCacheFallback({ nextAsk, sayText, cachedChoice });
  return (nextAsk || null) as any;
}

function updateChoiceCacheFromAsk(state: ChatState, ask: Ask | null): ChatState {
  if (!ask || String(ask.type || "") !== "choice") return state;
  const opts = Array.isArray((ask as any).options) ? (ask as any).options : [];
  if (opts.length === 0) return state;
  return {
    ...state,
    cachedChoice: {
      prompt: String(ask.prompt || "").trim() || undefined,
      options: opts,
    },
  };
}

function maybePushBot(state: ChatState, text: string, suppressIfAskCard: boolean): ChatState {
  const t = String(text || "").trim();
  if (!t) return state;
  if (lastBotText(state.bubbles).trim() === t) return state;
  const next: ChatState = {
    ...state,
    bubbles: [...state.bubbles, { id: uid(), role: "bot", text: t, suppressIfAskCard }],
  };
  return maybeSetReservation(next, t);
}

export function initialChatState(args: {
  cachedChoice: ChatState["cachedChoice"];
  lastPassenger: PassengerSnap | null;
  debug: boolean;
}): ChatState {
  return {
    serverState: {},
    ask: null,
    bubbles: [],
    loading: false,
    pendingAskSig: null,
    cachedChoice: args.cachedChoice,
    lastPassenger: args.lastPassenger,
    reservation: null,
    debug: args.debug,
  };
}

export function chatReducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case "SET_DEBUG":
      return { ...state, debug: action.debug };

    case "BOOT_START":
      return { ...state, loading: true, pendingAskSig: action.pendingAskSig, bubbles: [], ask: null, reservation: null };

    case "BOOT_OK": {
      const env = action.env;
      const serverState = (env.state || {}) as Record<string, unknown>;
      const ask = normalizeEnvAsk(env, action.cachedChoice);

      const sayText = String(env.say || "").trim();
      const promptText = String((ask as any)?.prompt || "").trim();
      const botText = String(sayText || promptText).trim();

      const renderAsk = willRenderAskCard(ask);
      let next: ChatState = {
        ...state,
        serverState,
        ask,
        bubbles: [],
        loading: false,
        pendingAskSig: null,
        lastPassenger: action.lastPassenger,
        cachedChoice: action.cachedChoice,
        reservation: null,
      };

      next = updateChoiceCacheFromAsk(next, ask);

      if (botText && !renderAsk) {
        next = { ...next, bubbles: [{ id: uid(), role: "bot", text: botText }] };
        next = maybeSetReservation(next, botText);
      } else if (botText) {
        // Ask card will render; only keep non-prompt status if needed.
        next = maybeSetReservation(next, botText);
      }
      return next;
    }

    case "BOOT_FAIL":
      return {
        ...state,
        loading: false,
        pendingAskSig: null,
        bubbles: [{ id: uid(), role: "bot", text: action.errorText }],
      };

    case "SEND_START": {
      const bubbles: ChatState["bubbles"] = action.echoUserText
        ? [...state.bubbles, { id: uid(), role: "user" as const, text: action.echoUserText }]
        : state.bubbles;
      return { ...state, loading: true, pendingAskSig: action.pendingAskSig, bubbles };
    }

    case "SEND_OK": {
      const env = action.env;
      const serverState = (env.state || {}) as Record<string, unknown>;
      const ask = normalizeEnvAsk(env, action.cachedChoice);

      let next: ChatState = {
        ...state,
        serverState,
        ask,
        loading: false,
        pendingAskSig: null,
      };

      next = updateChoiceCacheFromAsk(next, ask);

      const sayText = String(env.say || "").trim();
      const botText = String(env.say || (ask as any)?.prompt || "").trim();
      const renderAsk = willRenderAskCard(ask);

      if (botText) {
        if (!renderAsk) {
          next = maybePushBot(next, botText, false);
        }
        // If an ask card will render, suppress the plain prompt bubble.
      }

      return next;
    }

    case "SEND_FAIL": {
      const bubbles: ChatState["bubbles"] = [...state.bubbles];
      if (action.userText) bubbles.push({ id: uid(), role: "user" as const, text: action.userText });
      bubbles.push({ id: uid(), role: "bot" as const, text: action.errorText });
      return { ...state, loading: false, pendingAskSig: null, bubbles };
    }

    case "SET_LAST_PASSENGER":
      return { ...state, lastPassenger: action.passenger };

    case "SET_RESERVATION":
      return { ...state, reservation: action.reservation };

    default:
      return state;
  }
}
