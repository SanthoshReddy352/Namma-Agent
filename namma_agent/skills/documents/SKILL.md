---
name: documents
description: >
  Read, summarize, compare and produce documents: PDFs, Word, PowerPoint,
  Excel, HTML and Markdown. Use when the user shares or names a document and
  asks what it says, wants a summary or comparison, or asks for a deliverable
  file ("make me a Word doc / PDF / slides of this"). Not for plain chat
  answers the user didn't ask to receive as a file.
platforms: [linux, macos, windows]
version: 1.0.0
category: documents
metadata:
  hermes:
    tags: [documents, pdf, docx, pptx, xlsx, summary]
---

# Documents

## Pick the approach

| Task | Approach |
|---|---|
| What does this file say / summarize it | `read_document`, then a sectioned summary |
| Compare two documents | `read_document` both, then a comparison table |
| Find a document | `find_files` with a pattern, then `read_document` |
| Make a Word / PDF / slides file | write Markdown, then `convert_document` with `to` |

## Procedure — summaries

1. Read the whole document (page through long ones with offsets).
2. Lead with what it is and its bottom line, then `## ` sections mirroring
   its structure, with the specific numbers, names and dates.
3. Quote sparingly and say where in the document each point comes from.

## Procedure — deliverables

1. Draft the content as clean Markdown: a title, `## ` sections, tables for
   tabular content. For slides, one `## ` heading per slide, few bullets each.
2. Call `convert_document` with the Markdown and `to` (docx, pdf, pptx…).
3. Give the user the download link and a one-line description of the file.

## Gotchas

- Scanned PDFs may have no text — say so and offer OCR (`read_text_from_image`).
- Never claim a file was created unless `convert_document` succeeded.
