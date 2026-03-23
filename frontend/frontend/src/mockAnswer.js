function pickKeywords(question) {
  return question
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length >= 4)
    .slice(0, 6);
}

function bestSnippetFromText(text, question) {
  if (!text?.trim()) return null;
  const keywords = pickKeywords(question);
  if (keywords.length === 0) return null;

  const paragraphs = text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);

  let best = { score: 0, para: null };
  for (const para of paragraphs) {
    const hay = ` ${para.toLowerCase()} `;
    let score = 0;
    for (const k of keywords) {
      if (hay.includes(` ${k} `)) score += 1;
    }
    if (score > best.score) best = { score, para };
  }

  if (!best.para || best.score === 0) return null;
  return best.para.length > 480 ? best.para.slice(0, 480) + "…" : best.para;
}

export function mockAnswer({ question, fileName, extractedText }) {
  const snippet = bestSnippetFromText(extractedText, question);
  if (snippet) {
    return {
      answer:
        `Offline mode: I searched your uploaded text and found this relevant part:\n\n` +
        snippet,
      sources: fileName ? [fileName] : [],
    };
  }

  return {
    answer:
      `Offline mode: backend is not connected, so I can’t run the RAG model. ` +
      `I did receive your question, but I can’t extract answers from this document type locally.` +
      (fileName ? ` (File: ${fileName})` : ""),
    sources: fileName ? [fileName] : [],
  };
}
