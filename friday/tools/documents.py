"""Document tool — extract readable text from a document file.

The v1 ``document_intel`` module was a full Chroma-backed RAG stack. The v2 port
keeps the useful, model-facing primitive: pull a document's text into the
conversation so the agent can read/summarise/answer over it. The model does the
"intelligence"; this tool just converts a file to text.

  read_document(path) — .txt/.md/.csv/.log directly; .pdf (pypdf); .docx (python-docx)

Plain-text formats need no dependency; PDF/DOCX use optional libraries and return
a clear error if they're missing. All paths go through PathSecurity.
"""
from __future__ import annotations

from pathlib import Path

from friday.core.safety import check_path
from friday.core.tools import ToolRegistry, ToolResult

_MAX_CHARS = 100_000
_PLAINTEXT = {".txt", ".md", ".markdown", ".csv", ".log", ".rst", ".json", ".yaml", ".yml"}


def _read_pdf(p: Path) -> str:
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("reading PDF needs the 'pypdf' package") from exc
    reader = PdfReader(str(p))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(p: Path) -> str:
    try:
        import docx  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("reading DOCX needs the 'python-docx' package") from exc
    return "\n".join(para.text for para in docx.Document(str(p)).paragraphs)


def _read_document(args: dict) -> ToolResult:
    path = (args.get("path") or "").strip()
    ok, reason = check_path(path)
    if not ok:
        return ToolResult(ok=False, content="", error=reason)
    p = Path(path).expanduser()
    if not p.is_file():
        return ToolResult(ok=False, content="", error=f"not a file: {path}")

    suffix = p.suffix.lower()
    try:
        if suffix in _PLAINTEXT:
            text = p.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            text = _read_pdf(p)
        elif suffix in (".docx",):
            text = _read_docx(p)
        else:
            return ToolResult(ok=False, content="",
                              error=f"unsupported document type: {suffix or '(none)'}")
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=str(exc))

    text = (text or "").strip()
    if not text:
        return ToolResult(ok=True, content="(document contained no extractable text)")
    truncated = len(text) > _MAX_CHARS
    return ToolResult(ok=True, content=text[:_MAX_CHARS] + ("\n…[truncated]" if truncated else ""),
                      data={"chars": len(text), "truncated": truncated})


def register(registry: ToolRegistry) -> None:
    registry.register("read_document",
        "Extract text from a document (.txt/.md/.csv/.pdf/.docx) for reading or summarising.", {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "path to the document file"}},
            "required": ["path"],
        }, _read_document)
