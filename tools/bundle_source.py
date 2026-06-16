"""Bundle all tool source files into one markdown reference (SOURCE_CODE.md)."""
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent

# (path relative to project root, language hint, one-line description)
FILES = [
    ("app/server.py", "python", "FastAPI web server — endpoints, review/verify jobs, audit log"),
    ("app/pipeline.py", "python", "Document conversion + Claude review & metadata-extraction calls"),
    ("app/jira_client.py", "python", "Jira Cloud client — pull FAIR attachments from a ticket"),
    ("app/__init__.py", "python", "Package marker"),
    ("app/static/index.html", "html", "Single-page UI — branding, upload, dashboard, edit, verify, review"),
    ("requirements.txt", "text", "Python dependencies"),
    ("run_secure.ps1", "powershell", "Localhost launcher (loads API key, binds 127.0.0.1)"),
    ("Start FAIR Review.bat", "bat", "Double-click launcher (bypasses script policy)"),
    ("tools/extract_pdf.py", "python", "Utility: PDF text -> markdown"),
    ("tools/extract_xls.py", "python", "Utility: Excel workbook -> markdown"),
    ("tools/pdf_to_png.py", "python", "Utility: render scanned PDF pages to PNG"),
    ("tools/backup.py", "python", "Rotating ZIP backup of all records"),
]

FENCE = "`" * 4  # 4-backtick fence survives any inner triple-backticks

lines = [
    "# FAIR Review Tool — Source Code",
    "",
    f"Generated {date.today().isoformat()} from the working project. "
    "Every file below is the actual source that runs the tool.",
    "",
    "## Files",
    "",
    "| File | Description |",
    "|---|---|",
]
for path, _lang, desc in FILES:
    lines.append(f"| `{path}` | {desc} |")
lines.append("")

total_lines = 0
for path, lang, desc in FILES:
    p = ROOT / path
    if not p.exists():
        lines += [f"## {path}", "", f"*(not found)*", ""]
        continue
    text = p.read_text(encoding="utf-8")
    total_lines += text.count("\n") + 1
    lines += [
        "---",
        "",
        f"## {path}",
        "",
        f"*{desc}*",
        "",
        f"{FENCE}{lang}",
        text.rstrip("\n"),
        FENCE,
        "",
    ]

out = ROOT / "SOURCE_CODE.md"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {out} — {len(FILES)} files, ~{total_lines} lines of code")
