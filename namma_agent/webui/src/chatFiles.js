// Phase 9 W1: the files a chat touched, for the side panel's Files and Preview
// tabs. Built from the transcript itself, so it needs no endpoint:
//  - generated media: every /api/media/<rel> reference in a message (the same
//    rule the chat export uses — core/chat_export.py `_MEDIA_URL_RE`);
//  - attachments the user sent (local uploads: listed, not previewable).

const MEDIA_URL_RE = /\/api\/media\/[^)\s"'<>]+/g;

const KINDS = [
  ["image", /\.(png|jpe?g|gif|webp|svg|avif|bmp)$/i],
  ["html", /\.html?$/i],
  ["pdf", /\.pdf$/i],
  ["audio", /\.(mp3|wav|ogg|m4a|flac)$/i],
  ["video", /\.(mp4|webm|mov)$/i],
  ["text", /\.(txt|md|csv|json|ya?ml|py|js|ts|jsx|tsx|css|log|xml|toml|ini|sh)$/i],
];

export function fileKind(name = "") {
  const clean = String(name).split(/[?#]/)[0];
  return (KINDS.find(([, re]) => re.test(clean)) || ["other"])[0];
}

const baseName = (p) => decodeURIComponent(String(p).split(/[?#]/)[0].split(/[\\/]/).pop() || p);

export function collectChatFiles(messages = []) {
  const seen = new Map();
  for (const m of messages) {
    for (const a of m.attachments || []) {
      const key = `att:${a.path || a.name}`;
      if (!seen.has(key)) {
        seen.set(key, { key, name: a.name || baseName(a.path), path: a.path, url: null,
                        kind: fileKind(a.name || a.path), source: "attachment", messageId: m.id });
      }
    }
    const text = typeof m.content === "string" ? m.content : "";
    for (const url of text.match(MEDIA_URL_RE) || []) {
      const clean = url.replace(/[.,;:!]+$/, "");          // trailing prose punctuation
      const key = `media:${clean.split(/[?#]/)[0]}`;
      if (!seen.has(key)) {
        seen.set(key, { key, name: baseName(clean), url: clean, path: null,
                        kind: fileKind(clean), source: "generated", messageId: m.id });
      }
    }
  }
  return [...seen.values()];
}
