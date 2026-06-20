"""convert_document — md → other formats, with stdlib-only fallbacks."""
from __future__ import annotations

import shutil
import zipfile

import pytest

from friday.core.tools import ToolRegistry
from friday.tools import load_tools
from friday.tools import convert as convert_mod

_SAMPLE = """\
# Trip Report

A short **intro** paragraph with *emphasis* and `code`.

## Findings

- first point
- second point with a [link](https://example.com)

1. step one
2. step two

> a quoted remark

| City | Status |
| ---- | ------ |
| Tada | outside center |
| Nellore | in center |

```python
print("hello")
```
"""


@pytest.fixture
def reg():
    return load_tools(ToolRegistry())


@pytest.fixture(autouse=True)
def _out_in_tmp(tmp_path, monkeypatch):
    """Redirect generated files into tmp so tests don't litter data/media."""
    monkeypatch.setattr(convert_mod, "_OUT_DIR", tmp_path / "documents")


def test_registered(reg):
    assert "convert_document" in reg


def test_requires_format(reg):
    r = reg.execute("convert_document", {"content": "# hi"})
    assert not r.ok and "to" in r.error.lower()


def test_requires_source(reg):
    r = reg.execute("convert_document", {"to": "txt"})
    assert not r.ok and ("content" in r.error or "path" in r.error)


def test_txt_fallback_strips_markdown(reg):
    r = reg.execute("convert_document", {"content": _SAMPLE, "to": "txt"})
    assert r.ok and r.data["format"] == "txt"
    path = convert_mod._OUT_DIR / r.data["url"].split("/")[-1]
    text = path.read_text(encoding="utf-8")
    assert "TRIP REPORT" in text          # heading upper-cased
    assert "**" not in text and "`" not in text  # markdown stripped
    assert "first point" in text and "step two" in text
    assert "outside center" in text       # table cell survived


def test_html_fallback_is_standalone(reg):
    r = reg.execute("convert_document", {"content": _SAMPLE, "to": "html", "title": "T"})
    assert r.ok
    html = (convert_mod._OUT_DIR / r.data["url"].split("/")[-1]).read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "<table>" in html and "<th>City</th>" in html
    assert "<strong>intro</strong>" in html
    assert '<a href="https://example.com">link</a>' in html


def test_aliases_and_download_link(reg):
    r = reg.execute("convert_document", {"content": "# Hi\n\nbody", "to": "Word"})
    # 'word' → docx. Needs python-docx OR pandoc; otherwise a clear install hint.
    if r.ok:
        assert r.data["format"] == "docx"
        assert "⬇ Download" in r.content
        path = convert_mod._OUT_DIR / r.data["url"].split("/")[-1]
        assert zipfile.is_zipfile(path)  # .docx is a zip container
    else:
        assert "docx" in r.error or "pandoc" in r.error


def test_unsupported_without_pandoc(reg, monkeypatch):
    monkeypatch.setattr(convert_mod.shutil, "which", lambda _: None)
    r = reg.execute("convert_document", {"content": "# x", "to": "epub"})
    assert not r.ok and "pandoc" in r.error


def test_from_md_file_path(reg, tmp_path):
    f = tmp_path / "note.md"
    f.write_text(_SAMPLE, encoding="utf-8")
    r = reg.execute("convert_document", {"path": str(f), "to": "txt"})
    assert r.ok and r.data["format"] == "txt"


def test_title_defaults_to_first_heading(reg):
    r = reg.execute("convert_document", {"content": "# My Heading\n\nx", "to": "txt"})
    assert r.ok and "My Heading" in r.content


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_pandoc_docx_roundtrip(reg):
    r = reg.execute("convert_document", {"content": _SAMPLE, "to": "docx"})
    assert r.ok and r.data["format"] == "docx"
    path = convert_mod._OUT_DIR / r.data["url"].split("/")[-1]
    assert zipfile.is_zipfile(path)
