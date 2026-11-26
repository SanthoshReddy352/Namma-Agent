import { useEffect, useState } from "react";
import { IconDownload, IconExternalLink } from "@tabler/icons-react";

// Phase 9 W1: the side panel's Preview tab. Shows one chat file inline:
// images, HTML (sandboxed, scripts allowed but no same-origin access), PDFs,
// audio/video, and text (first 200 KB). Uploads aren't served over HTTP, so
// they get a note instead of a preview.
const TEXT_CAP = 200_000;

export default function FilePreview({ file }) {
  if (!file) {
    return <p className="text-sm text-fg-muted">Pick a file in Files to preview it here.</p>;
  }
  return (
    <div className="flex flex-col gap-2 h-full min-h-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-sm font-medium text-fg truncate flex-1" title={file.name}>{file.name}</span>
        {file.url && (
          <>
            <a href={file.url} target="_blank" rel="noreferrer" aria-label="Open in a new tab" title="Open in a new tab"
               className="grid place-items-center h-6 w-6 rounded-sm text-fg-muted hover:text-fg hover:bg-surface-sunken">
              <IconExternalLink size={14} stroke={1.8} aria-hidden="true" />
            </a>
            <a href={file.url} download aria-label="Download" title="Download"
               className="grid place-items-center h-6 w-6 rounded-sm text-fg-muted hover:text-fg hover:bg-surface-sunken">
              <IconDownload size={14} stroke={1.8} aria-hidden="true" />
            </a>
          </>
        )}
      </div>
      <div className="flex-1 min-h-0 rounded-md border border-border bg-bg overflow-auto">
        <PreviewBody file={file} />
      </div>
    </div>
  );
}

function PreviewBody({ file }) {
  if (!file.url) {
    return <p className="p-3 text-sm text-fg-muted">You attached this file from your computer. The agent can read it, but it isn't served to the browser, so there's no preview.</p>;
  }
  switch (file.kind) {
    case "image":
      return <img src={file.url} alt={file.name} className="block max-w-full h-auto mx-auto" />;
    case "html":
      return <iframe title={file.name} src={file.url} sandbox="allow-scripts" className="w-full h-full min-h-[24rem] bg-surface" />;
    case "pdf":
      return <iframe title={file.name} src={file.url} className="w-full h-full min-h-[24rem]" />;
    case "audio":
      return <audio controls src={file.url} className="w-full p-2" />;
    case "video":
      return <video controls src={file.url} className="w-full" />;
    case "text":
      return <TextPreview url={file.url} />;
    default:
      return <p className="p-3 text-sm text-fg-muted">No preview for this file type. Open or download it instead.</p>;
  }
}

function TextPreview({ url }) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let live = true;
    setState({ loading: true });
    fetch(url).then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((t) => live && setState({ text: t.length > TEXT_CAP ? t.slice(0, TEXT_CAP) : t, cut: t.length > TEXT_CAP }))
      .catch(() => live && setState({ error: true }));
    return () => { live = false; };
  }, [url]);
  if (state.loading) return <p className="p-3 text-sm text-fg-muted">Loading…</p>;
  if (state.error) return <p className="p-3 text-sm text-danger">Couldn't load this file.</p>;
  return (
    <>
      <pre className="p-3 text-xs font-mono whitespace-pre-wrap break-words text-fg">{state.text}</pre>
      {state.cut && <p className="px-3 pb-3 text-xs text-fg-subtle">Showing the first 200 KB. Download it for the rest.</p>}
    </>
  );
}
