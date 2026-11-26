---
name: data-analysis
description: >
  Analyze a data file (CSV, Excel, JSON) or a pasted table: load it, clean it,
  compute the numbers that answer the question, and present the result as a
  table plus a chart. Use when the user asks to analyze, summarize, total,
  average, find trends or outliers in data, or "make a chart from this file".
  Not for a single number you can read straight off a short table.
platforms: [linux, macos, windows]
version: 1.0.0
category: data
metadata:
  hermes:
    tags: [data, csv, excel, analysis, charts]
---

# Data Analysis

Numbers you compute with code are trustworthy; numbers you eyeball are not.

## Procedure

1. **Look first.** `read_document` (or `read_file` for small CSV/JSON) to see
   the columns, types and a few rows. Note units, missing values, odd rows.
2. **Compute with Python** via `run_shell` — `python -c` or a short script
   written with `write_file`. Use pandas when it imports; otherwise the `csv`
   and `statistics` modules. Print exactly the figures you need.
3. **Check the result** against the raw data once (a row count, one total by
   hand) before reporting it.
4. **Present:**
   - the answer in one or two sentences first;
   - a markdown table of the key figures;
   - a ```chart block (bar for categories, line for time, pie for shares —
     one number per label);
   - caveats (missing data, assumptions).

## Gotchas

- Dates and thousands separators often parse as text — convert explicitly.
- Never invent values for missing data; say what was excluded.
- Large files: aggregate in code and show the summary, not the raw rows.
