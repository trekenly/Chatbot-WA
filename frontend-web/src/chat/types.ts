export type Role = "bot" | "user";

export type Bubble = {
  id: string;
  role: Role;
  text: string;
  /**
   * When true, this assistant bubble should be hidden if we render an ask-card UI
   * for the same turn (prevents duplicate prompt bubbles).
   */
  suppressIfAskCard?: boolean;
};

export type AskOption = {
  value: string;
  label?: string;
};

// Keep Ask intentionally loose to match backend envelope.
export type Ask = {
  type?: string;
  field?: string;
  prompt?: string;
  options?: AskOption[];
  [k: string]: unknown;
};

export type ChatEnv = {
  say?: string;
  ask?: Ask | null;
  state?: Record<string, unknown>;
  [k: string]: unknown;
};

export type CachedChoice = {
  prompt?: string;
  options: any[];
};

export type PassengerSnap = {
  title?: string;
  gender?: string;
  firstName?: string;
  lastName?: string;
  email?: string;
  phone?: string;
};

export type ChatState = {
  serverState: Record<string, unknown>;
  ask: Ask | null;
  bubbles: Bubble[];
  loading: boolean;

  // UI helpers
  pendingAskSig: string | null;
  cachedChoice: CachedChoice;
  lastPassenger: PassengerSnap | null;
  reservation: any | null;
  debug: boolean;
};
