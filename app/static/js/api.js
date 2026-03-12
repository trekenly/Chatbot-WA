export async function chat({ endpoint, userId, text, state }) {
  const payload = {
    user_id: userId,
    text: String(text ?? ""),
    state: state ?? {},
    locale: "en_US",
    time_zone: "Asia/Bangkok",
    currency: "THB",
  };

  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
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

  return await res.json();
}
