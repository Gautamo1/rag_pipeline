const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export async function checkHealth({ timeoutMs = 1500 } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}/health`, {
      signal: controller.signal,
    });
    if (!res.ok) return { ok: false };
    const json = await res.json();
    return { ok: json?.status === "ok", details: json };
  } catch {
    return { ok: false };
  } finally {
    clearTimeout(timeout);
  }
}

export async function queryFile({ file, question, timeoutMs = 60000 } = {}) {
  if (!file) throw new Error("Missing file");
  if (!question?.trim()) throw new Error("Missing question");

  const form = new FormData();
  form.append("file", file);
  form.append("questions", JSON.stringify([question]));

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${API_BASE}/query-file`, {
      method: "POST",
      body: form,
      signal: controller.signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `Request failed (${res.status})`);
    }

    const json = await res.json();
    const first = json?.results?.[0];
    return {
      answer: first?.answer || "No answer returned.",
      sources: first?.sources || [],
      raw: json,
    };
  } finally {
    clearTimeout(timeout);
  }
}
