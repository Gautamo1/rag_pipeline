import React, { useEffect, useRef, useState } from "react";
import { checkHealth, queryFile } from "./api.js";
import { mockAnswer } from "./mockAnswer.js";

function formatSources(sources) {
  if (!sources || sources.length === 0) return "";
  return `Sources: ${sources.join(", ")}`;
}

async function extractTextIfPlain(file) {
  if (!file) return "";
  const name = file.name.toLowerCase();
  const looksPlain =
    name.endsWith(".txt") ||
    name.endsWith(".md") ||
    name.endsWith(".csv") ||
    name.endsWith(".json");

  if (!looksPlain) return "";
  try {
    return await file.text();
  } catch {
    return "";
  }
}

export default function App() {
  const [backendOnline, setBackendOnline] = useState(false);

  const [file, setFile] = useState(null);
  const [extractedText, setExtractedText] = useState("");

  const [messages, setMessages] = useState([
    {
      id: crypto.randomUUID(),
      role: "assistant",
      text: "Upload a policy document, then ask questions in chat.",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const listRef = useRef(null);
  const fileName = file?.name || "";

  useEffect(() => {
    (async () => {
      const health = await checkHealth();
      setBackendOnline(Boolean(health.ok));
    })();
  }, []);

  useEffect(() => {
    if (!listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, busy]);

  async function onPickFile(e) {
    const picked = e.target.files?.[0] || null;
    setError("");
    setFile(picked);
    setDraft("");

    if (!picked) {
      setExtractedText("");
      return;
    }

    const text = await extractTextIfPlain(picked);
    setExtractedText(text);

    setMessages((m) => [
      ...m,
      {
        id: crypto.randomUUID(),
        role: "assistant",
        text: `Got it. Uploaded: ${picked.name}. Ask me something about the policy.`,
      },
    ]);
  }

  async function send() {
    const question = draft.trim();
    if (!question) return;

    setError("");
    setDraft("");

    const userMsg = { id: crypto.randomUUID(), role: "user", text: question };
    setMessages((m) => [...m, userMsg]);

    setBusy(true);
    try {
      if (backendOnline && file) {
        const res = await queryFile({ file, question });
        const extra = formatSources(res.sources);
        setMessages((m) => [
          ...m,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            text: res.answer + (extra ? `\n\n${extra}` : ""),
          },
        ]);
      } else {
        const res = mockAnswer({ question, fileName, extractedText });
        const extra = formatSources(res.sources);
        setMessages((m) => [
          ...m,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            text: res.answer + (extra ? `\n\n${extra}` : ""),
          },
        ]);
      }
    } catch (e) {
      setError(e?.message || String(e));
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: "I hit an error talking to the backend. Falling back to offline mode for now.",
        },
      ]);
      setBackendOnline(false);

      const res = mockAnswer({ question, fileName, extractedText });
      const extra = formatSources(res.sources);
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: res.answer + (extra ? `\n\n${extra}` : ""),
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!busy) send();
    }
  }

  return (
    <div className="page">
      <header className="header">
        <div className="title">
          LLM Based Query Retrieval System (Policy Q&amp;A)
        </div>
      </header>

      <main className="main">
        <section className="panel">
          <div className="panelTitle">1) Upload document</div>

          <div className="uploadRow">
            <label className="uploadButton">
              <input
                className="fileInput"
                type="file"
                accept=".pdf,.doc,.docx,.txt,.md"
                onChange={onPickFile}
              />
              <span>{file ? "Change file" : "Upload file"}</span>
            </label>

            <div className="fileMeta">
              <div className="fileName">
                {file ? file.name : "No file selected"}
              </div>
              <div className="fileHint">Supported: PDF, DOC/DOCX, TXT, MD</div>
            </div>
          </div>

          {file && extractedText && (
            <div className="note">
              Offline helper: text extraction is enabled for plain text/markdown
              files.
            </div>
          )}
        </section>

        <section className="panel chatPanel">
          <div className="panelTitle">2) Ask questions</div>

          <div ref={listRef} className="chatList" aria-live="polite">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={msg.role === "user" ? "bubble user" : "bubble bot"}
              >
                {msg.text.split("\n").map((line, idx) => (
                  <div key={idx} className="line">
                    {line}
                  </div>
                ))}
              </div>
            ))}

            {busy && (
              <div className="bubble bot">
                <div className="line">Thinking…</div>
              </div>
            )}
          </div>

          <div className="composer">
            <textarea
              className="input"
              placeholder={
                file
                  ? "Type a policy question (e.g., What is the policy number?)"
                  : "Upload a document first…"
              }
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={busy || !file}
              rows={2}
            />
            <button
              className="sendButton"
              onClick={send}
              disabled={busy || !file}
            >
              Send
            </button>
          </div>

          {error && <div className="error">{error}</div>}
        </section>
      </main>
    </div>
  );
}
