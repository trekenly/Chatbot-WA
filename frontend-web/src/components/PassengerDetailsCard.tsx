import { useEffect, useMemo, useRef, useState } from "react";

type Props = {
  disabled?: boolean;
  onSubmit: (payloadText: string) => void;
};

const LS_PASSENGER = "busx_passenger";

function safeGet(key: string): string {
  try {
    return String(localStorage.getItem(key) || "");
  } catch {
    return "";
  }
}

function safeSet(key: string, value: string) {
  try {
    localStorage.setItem(key, String(value || ""));
  } catch {
    // ignore
  }
}

function safeDel(key: string) {
  try {
    localStorage.removeItem(key);
  } catch {
    // ignore
  }
}

function normalizeThaiPhone(v: string): string {
  let s = String(v || "");
  s = s.replace(/\D+/g, "");
  if (s.startsWith("0066")) s = "66" + s.slice(4);
  if (s.startsWith("66")) s = "0" + s.slice(2);
  if (s.length > 10) s = s.slice(0, 10);
  return s;
}

function isValidEmail(v: string): boolean {
  const t = (v || "").trim();
  // simple, practical check
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(t);
}

export function PassengerDetailsCard({ disabled, onSubmit }: Props) {
  const [title, setTitle] = useState<"Mr" | "Ms">("Mr");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [err, setErr] = useState<string>("");
  const [hasSaved, setHasSaved] = useState(false);

  const firstRef = useRef<HTMLInputElement | null>(null);
  const lastRef = useRef<HTMLInputElement | null>(null);
  const emailRef = useRef<HTMLInputElement | null>(null);
  const phoneRef = useRef<HTMLInputElement | null>(null);

  const gender = useMemo(() => (title === "Mr" ? "M" : "F"), [title]);
  const titleId = useMemo(() => (title === "Mr" ? 1 : 2), [title]);

  useEffect(() => {
    const raw = safeGet(LS_PASSENGER);
    setHasSaved(!!raw);
  }, []);

  function loadSaved() {
    const raw = safeGet(LS_PASSENGER);
    if (!raw) return;
    try {
      const p = JSON.parse(raw);
      if (p?.title === "Mr" || p?.title === "Ms") setTitle(p.title);
      if (typeof p?.first === "string") setFirst(p.first);
      if (typeof p?.last === "string") setLast(p.last);
      if (typeof p?.email === "string") setEmail(p.email);
      if (typeof p?.phone === "string") setPhone(normalizeThaiPhone(p.phone));
      setErr("");
      firstRef.current?.focus();
    } catch {
      // bad saved value, clear
      safeDel(LS_PASSENGER);
      setHasSaved(false);
    }
  }

  function validate(): boolean {
    const f = first.trim();
    const l = last.trim();
    const e = email.trim();
    const p = normalizeThaiPhone(phone);

    if (!title) {
      setErr("Title is required.");
      return false;
    }
    if (!f) {
      setErr("First name is required.");
      firstRef.current?.focus();
      return false;
    }
    if (!l) {
      setErr("Last name is required.");
      lastRef.current?.focus();
      return false;
    }
    if (!e) {
      setErr("Email is required.");
      emailRef.current?.focus();
      return false;
    }
    if (!isValidEmail(e)) {
      setErr("Please enter a valid email.");
      emailRef.current?.focus();
      return false;
    }
    if (!p) {
      setErr("Phone is required.");
      phoneRef.current?.focus();
      return false;
    }
    if (p.length !== 10 || !p.startsWith("0")) {
      setErr("Phone number should be 10 digits (example: 0812345678).");
      phoneRef.current?.focus();
      return false;
    }
    setErr("");
    return true;
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;

    const payload = {
      title: title,
      title_id: titleId,
      first: first.trim(),
      last: last.trim(),
      email: email.trim(),
      phone: normalizeThaiPhone(phone),
      country: "TH",
      gender,
    };

    // Save for next purchase (reduces re-typing friction)
    safeSet(
      LS_PASSENGER,
      JSON.stringify({
        title: payload.title,
        first: payload.first,
        last: payload.last,
        email: payload.email,
        phone: payload.phone,
      })
    );
    setHasSaved(true);

    onSubmit(JSON.stringify(payload));
  }

  return (
    <form onSubmit={submit}>
      <div style={{ fontWeight: 800, marginBottom: 10 }}>Passenger details</div>

      {hasSaved ? (
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
          <button className="chip" type="button" disabled={disabled} onClick={loadSaved}>
            Use saved details
          </button>
          <button
            className="chip"
            type="button"
            disabled={disabled}
            onClick={() => {
              safeDel(LS_PASSENGER);
              setHasSaved(false);
            }}
            title="Remove saved passenger details from this browser"
          >
            Clear saved
          </button>
        </div>
      ) : null}

      <div className="grid2" style={{ marginBottom: 10 }}>
        <div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Title</div>
          <select value={title} onChange={(e) => setTitle(e.target.value as any)} disabled={disabled}>
            <option value="Mr">Mr</option>
            <option value="Ms">Ms</option>
          </select>
        </div>
        <div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Gender (auto)</div>
          <input type="text" value={gender === "M" ? "Male" : "Female"} disabled />
        </div>
      </div>

      <div className="grid2">
        <div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>First name</div>
          <input
            ref={firstRef}
            type="text"
            value={first}
            onChange={(e) => setFirst(e.target.value)}
            disabled={disabled}
          />
        </div>
        <div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Last name</div>
          <input
            ref={lastRef}
            type="text"
            value={last}
            onChange={(e) => setLast(e.target.value)}
            disabled={disabled}
          />
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Email</div>
        <input
          ref={emailRef}
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={disabled}
        />
      </div>

      <div style={{ marginTop: 10 }}>
        <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Phone (Thailand)</div>
        <input
          ref={phoneRef}
          type="text"
          value={phone}
          onChange={(e) => setPhone(normalizeThaiPhone(e.target.value))}
          placeholder="0812345678"
          disabled={disabled}
        />
      </div>

      {err && <div className="err">{err}</div>}

      <div style={{ marginTop: 10, display: "grid" }}>
        <button className="btn btnPrimary" type="submit" disabled={disabled}>
          Continue
        </button>
      </div>
    </form>
  );
}
