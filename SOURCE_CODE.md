# FAIR Review Tool — Source Code

Generated 2026-06-15 from the working project. Every file below is the actual source that runs the tool.

## Files

| File | Description |
|---|---|
| `app/server.py` | FastAPI web server — endpoints, review/verify jobs, audit log |
| `app/pipeline.py` | Document conversion + Claude review & metadata-extraction calls |
| `app/jira_client.py` | Jira Cloud client — pull FAIR attachments from a ticket |
| `app/__init__.py` | Package marker |
| `app/static/index.html` | Single-page UI — branding, upload, dashboard, edit, verify, review |
| `requirements.txt` | Python dependencies |
| `run_secure.ps1` | Localhost launcher (loads API key, binds 127.0.0.1) |
| `Start FAIR Review.bat` | Double-click launcher (bypasses script policy) |
| `tools/extract_pdf.py` | Utility: PDF text -> markdown |
| `tools/extract_xls.py` | Utility: Excel workbook -> markdown |
| `tools/pdf_to_png.py` | Utility: render scanned PDF pages to PNG |
| `tools/backup.py` | Rotating ZIP backup of all records |

---

## app/server.py

*FastAPI web server — endpoints, review/verify jobs, audit log*

````python
"""Skyryse FAIR Review — web app.

Run with:  python -m uvicorn app.server:app --host 0.0.0.0 --port 8000
(from the project root, with ANTHROPIC_API_KEY set)
"""
from __future__ import annotations

import getpass
import json
import re
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import pipeline

ROOT_DIR = Path(__file__).resolve().parent.parent
PARTS_DIR = ROOT_DIR / "parts"
PARTS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Skyryse FAIR Review")

ALLOWED_EXTS = {
    ".pdf", ".xls", ".xlsx", ".xlsm", ".docx", ".doc", ".txt", ".md", ".csv",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff",
}


def _safe_id(part_number: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", part_number.strip())
    if not cleaned or cleaned in (".", ".."):
        raise HTTPException(400, "Invalid part number")
    return cleaned


def _meta_path(part_id: str) -> Path:
    return PARTS_DIR / part_id / "part.json"


def _load_meta(part_id: str) -> dict:
    p = _meta_path(part_id)
    if not p.exists():
        raise HTTPException(404, f"Part {part_id} not found")
    return json.loads(p.read_text(encoding="utf-8"))


def _save_meta(part_id: str, meta: dict) -> None:
    _meta_path(part_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")


_AUDIT_PATH = ROOT_DIR / "audit.log"
_audit_lock = threading.Lock()


def _audit(action: str, part_id: str, detail: str = "") -> None:
    """Append-only audit trail for AS9100/AS9102 records retention."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": getpass.getuser(),
        "action": action,
        "part": part_id,
        "detail": detail,
    }
    with _audit_lock:
        with _AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


@app.get("/api/parts")
def list_parts():
    parts = []
    for d in sorted(PARTS_DIR.iterdir()):
        if (d / "part.json").exists():
            meta = json.loads((d / "part.json").read_text(encoding="utf-8"))
            parts.append({
                "id": meta["id"],
                "part_number": meta["part_number"],
                "part_name": meta.get("part_name", ""),
                "revision": meta.get("revision", ""),
                "supplier": meta.get("supplier", ""),
                "po_number": meta.get("po_number", ""),
                "status": meta.get("status", "new"),
                "verdict": meta.get("verdict"),
                "created_at": meta.get("created_at"),
                "file_count": len(list((d / "uploads").glob("*"))) if (d / "uploads").exists() else 0,
            })
    parts.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return parts


@app.post("/api/parts")
async def create_part(
    part_number: str = Form(...),
    revision: str = Form(""),
    part_name: str = Form(""),
    supplier: str = Form(""),
    po_number: str = Form(""),
    notes: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    part_id = _safe_id(part_number)
    part_dir = PARTS_DIR / part_id
    uploads_dir = part_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    if _meta_path(part_id).exists():
        meta = _load_meta(part_id)
    else:
        meta = {
            "id": part_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "new",
            "verdict": None,
        }
    meta.update({
        "part_number": part_number.strip(),
        "revision": revision.strip(),
        "part_name": part_name.strip(),
        "supplier": supplier.strip(),
        "po_number": po_number.strip(),
        "notes": notes.strip(),
    })

    is_new = "files" not in meta or not meta.get("files")
    saved = await _save_uploads(uploads_dir, files)
    meta.setdefault("files", [])
    meta["files"] = sorted(set(meta["files"]) | set(saved))
    _save_meta(part_id, meta)
    _audit("part_created" if is_new else "part_updated", part_id,
           f"files added: {', '.join(saved) or 'none'}")
    return {"id": part_id, "saved_files": saved}


@app.post("/api/parts/{part_id}/files")
async def add_files(part_id: str, files: list[UploadFile] = File(...)):
    meta = _load_meta(part_id)
    uploads_dir = PARTS_DIR / part_id / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    saved = await _save_uploads(uploads_dir, files)
    meta.setdefault("files", [])
    meta["files"] = sorted(set(meta["files"]) | set(saved))
    _save_meta(part_id, meta)
    _audit("files_added", part_id, f"files added: {', '.join(saved) or 'none'}")
    return {"saved_files": saved}


@app.post("/api/parts/{part_id}/edit")
def edit_part(
    part_id: str,
    part_number: str = Form(...),
    revision: str = Form(""),
    part_name: str = Form(""),
    supplier: str = Form(""),
    po_number: str = Form(""),
    notes: str = Form(""),
):
    meta = _load_meta(part_id)
    if meta.get("status") == "reviewing":
        raise HTTPException(409, "Cannot edit while a review is running")

    new_pn = part_number.strip()
    if not new_pn:
        raise HTTPException(400, "Part number is required")
    new_id = _safe_id(new_pn)

    # If the part number (and therefore the record id) changed, move the folder.
    if new_id != part_id:
        target = PARTS_DIR / new_id
        if target.exists():
            raise HTTPException(409, f"A part with id '{new_id}' already exists")
        (PARTS_DIR / part_id).rename(target)
        old_report = target / f"REVIEW_{part_id}.md"
        if old_report.exists():
            old_report.rename(target / f"REVIEW_{new_id}.md")
        meta["id"] = new_id
        part_id = new_id

    meta.update({
        "part_number": new_pn,
        "revision": revision.strip(),
        "part_name": part_name.strip(),
        "supplier": supplier.strip(),
        "po_number": po_number.strip(),
        "notes": notes.strip(),
    })
    _save_meta(part_id, meta)
    _audit("part_edited", part_id, f"pn={new_pn} po={po_number.strip()} supplier={supplier.strip()}")
    return {"id": part_id}


def _verify_job(part_id: str) -> None:
    part_dir = PARTS_DIR / part_id
    meta = _load_meta(part_id)
    try:
        found = pipeline.extract_metadata(part_dir)
        meta["extracted"] = found
        meta["verifying"] = False
        meta.pop("verify_error", None)
        _audit("verified", part_id, "metadata read from documents")
    except Exception as exc:
        meta["verifying"] = False
        meta["verify_error"] = f"{exc}"
        (part_dir / "verify_error.log").write_text(traceback.format_exc(), encoding="utf-8")
    _save_meta(part_id, meta)


@app.post("/api/parts/{part_id}/verify")
def start_verify(part_id: str):
    meta = _load_meta(part_id)
    uploads = list((PARTS_DIR / part_id / "uploads").glob("*"))
    if not uploads:
        raise HTTPException(400, "Upload at least one document first")
    if meta.get("verifying"):
        raise HTTPException(409, "Verification already in progress")
    meta["verifying"] = True
    _save_meta(part_id, meta)
    threading.Thread(target=_verify_job, args=(part_id,), daemon=True).start()
    return {"verifying": True}


async def _save_uploads(uploads_dir: Path, files: list[UploadFile]) -> list[str]:
    saved = []
    for f in files:
        if not f.filename:
            continue
        name = Path(f.filename).name  # strip any path components
        if Path(name).suffix.lower() not in ALLOWED_EXTS:
            raise HTTPException(400, f"Unsupported file type: {name}")
        (uploads_dir / name).write_bytes(await f.read())
        saved.append(name)
    return saved


@app.get("/api/parts/{part_id}")
def get_part(part_id: str):
    meta = _load_meta(part_id)
    review_path = PARTS_DIR / part_id / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else None
    return {"meta": meta, "review": review}


@app.get("/api/parts/{part_id}/files/{name}")
def download_file(part_id: str, name: str):
    path = PARTS_DIR / part_id / "uploads" / Path(name).name
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path)


@app.get("/api/parts/{part_id}/report.md")
def download_report(part_id: str):
    path = PARTS_DIR / part_id / f"REVIEW_{part_id}.md"
    if not path.exists():
        raise HTTPException(404, "No report yet")
    return FileResponse(path, media_type="text/markdown", filename=path.name)


def _run_review_job(part_id: str) -> None:
    part_dir = PARTS_DIR / part_id
    meta = _load_meta(part_id)
    try:
        review = pipeline.run_review(part_dir, meta)
        (part_dir / "review.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
        (part_dir / f"REVIEW_{part_id}.md").write_text(
            pipeline.review_to_markdown(review, meta), encoding="utf-8"
        )
        meta["status"] = "reviewed"
        meta["verdict"] = review.get("verdict")
        meta["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        meta.pop("error", None)
        _audit("review_completed", part_id, f"verdict: {review.get('verdict')}")
    except Exception as exc:
        meta["status"] = "error"
        meta["error"] = f"{exc}"
        (part_dir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        _audit("review_error", part_id, f"{exc}")
    _save_meta(part_id, meta)


@app.post("/api/parts/{part_id}/review")
def start_review(part_id: str):
    meta = _load_meta(part_id)
    if meta.get("status") == "reviewing":
        raise HTTPException(409, "Review already in progress")
    uploads = list((PARTS_DIR / part_id / "uploads").glob("*"))
    if not uploads:
        raise HTTPException(400, "Upload at least one document first")
    meta["status"] = "reviewing"
    _save_meta(part_id, meta)
    _audit("review_started", part_id, f"{len(uploads)} document(s)")
    threading.Thread(target=_run_review_job, args=(part_id,), daemon=True).start()
    return {"status": "reviewing"}


@app.exception_handler(Exception)
async def unhandled(request, exc):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# Static frontend — mounted last so /api routes win.
app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True), name="static")
````

---

## app/pipeline.py

*Document conversion + Claude review & metadata-extraction calls*

````python
"""Document conversion + AI FAIR review pipeline.

Converts supplier documents (PDF / Excel / Word / images) into Claude-readable
content blocks, then runs a single structured review against the Skyryse
Supplier Quality Clauses and AS9102 requirements.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import anthropic
import pandas as pd
import pdfplumber
import pypdfium2 as pdfium

MODEL = "claude-opus-4-8"
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
CLAUSES_PATH = ROOT_DIR / "Skyryse Quality Clauses.md"

# A scanned page typically extracts as empty or garbage; below this many
# characters we fall back to rendering the page as an image.
MIN_TEXT_CHARS_PER_PAGE = 40
RENDER_SCALE = 2.0  # ~144 DPI, enough for cert fine print


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def _png_block(pil_image) -> dict:
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(buf.getvalue()).decode(),
        },
    }


def convert_pdf(path: Path) -> list[dict]:
    """Text pages become text blocks; scanned pages become image blocks."""
    blocks: list[dict] = []
    with pdfplumber.open(path) as pdf:
        texts = [page.extract_text() or "" for page in pdf.pages]
    doc = pdfium.PdfDocument(str(path))
    try:
        for i, text in enumerate(texts):
            if len(text.strip()) >= MIN_TEXT_CHARS_PER_PAGE:
                blocks.append({"type": "text", "text": f"[Page {i + 1}]\n{text}"})
            else:
                blocks.append({"type": "text", "text": f"[Page {i + 1} — scanned image follows]"})
                blocks.append(_png_block(doc[i].render(scale=RENDER_SCALE).to_pil()))
    finally:
        doc.close()
    return blocks


def convert_excel(path: Path) -> list[dict]:
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    parts = []
    for name, df in sheets.items():
        df = df.fillna("")
        lines = [f"## Sheet: {name}"]
        for idx, row in df.iterrows():
            cells = [str(c).strip() for c in row.tolist()]
            if any(cells):
                rendered = " | ".join(
                    f"[col {i + 1}] {c}" for i, c in enumerate(cells) if c
                )
                lines.append(f"Row {idx + 1}: {rendered}")
        parts.append("\n".join(lines))
    return [{"type": "text", "text": "\n\n".join(parts)}]


def convert_docx(path: Path) -> list[dict]:
    import docx

    d = docx.Document(str(path))
    lines = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    return [{"type": "text", "text": "\n".join(lines)}]


def convert_image(path: Path) -> list[dict]:
    from PIL import Image

    return [_png_block(Image.open(path).convert("RGB"))]


def convert_file(path: Path) -> list[dict]:
    """Return Claude content blocks for one uploaded file, prefixed with a header."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            blocks = convert_pdf(path)
        elif ext in (".xls", ".xlsx", ".xlsm"):
            blocks = convert_excel(path)
        elif ext == ".docx":
            blocks = convert_docx(path)
        elif ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff"):
            blocks = convert_image(path)
        else:
            blocks = [{"type": "text", "text": path.read_text(encoding="utf-8", errors="replace")}]
    except Exception as exc:  # surface conversion failure to the reviewer
        blocks = [{"type": "text", "text": f"[CONVERSION FAILED for this file: {exc}]"}]
    header = {"type": "text", "text": f"\n===== DOCUMENT: {path.name} ====="}
    return [header, *blocks]


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["APPROVED", "UNAPPROVED", "NEEDS_INFO"]},
        "part_number": {"type": "string"},
        "part_name": {"type": "string"},
        "supplier": {"type": "string"},
        "po_number": {"type": "string"},
        "summary": {
            "type": "string",
            "description": "Short plain-English summary: does the part have full traceability from the OEM to Skyryse? If not, why not.",
        },
        "traceability_complete": {"type": "boolean"},
        "traceability_chain": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "string", "description": "Role in the chain, e.g. Mill, Distributor, OCM, Special Process"},
                    "entity": {"type": "string"},
                    "document": {"type": "string", "description": "Document name and page that evidences this step"},
                    "key_ids": {"type": "string", "description": "Heat/lot/cert/PO numbers tying this step to the next"},
                    "linked": {"type": "boolean", "description": "Is this step documentarily linked to the next step?"},
                },
                "required": ["step", "entity", "document", "key_ids", "linked"],
                "additionalProperties": False,
            },
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["major", "minor", "observation"]},
                    "category": {"type": "string", "description": "e.g. Traceability, AS9102 Form 1/2/3, Special Process, CoC, Material"},
                    "description": {"type": "string"},
                    "location": {"type": "string", "description": "Exact document name and page/sheet/block where the reviewer can verify this"},
                    "required_action": {"type": "string"},
                },
                "required": ["severity", "category", "description", "location", "required_action"],
                "additionalProperties": False,
            },
        },
        "clarifying_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "verdict", "part_number", "part_name", "supplier", "po_number", "summary",
        "traceability_complete", "traceability_chain", "findings", "clarifying_questions",
    ],
    "additionalProperties": False,
}


def _system_prompt() -> str:
    clauses = ""
    if CLAUSES_PATH.exists():
        clauses = CLAUSES_PATH.read_text(encoding="utf-8")
    return f"""You are a Quality Engineer at Skyryse experienced in AS9102 First Article Inspection Report (FAIR) review and acceptance. You review FAIR packages submitted by suppliers for completeness, accuracy, continuity, and traceability.

Review rules:
- Treat the Skyryse Supplier Quality Clauses below as flow-down requirements, alongside AS9102 (latest revision) and all controlling drawings, specifications, and purchase order requirements that appear in the package.
- Verify FULL traceability from the OEM/mill through every intermediary (every distributor must have a transactional document — packing slip, invoice, or cert — linking it to the next party) to Skyryse as the customer. A missing intermediary link is a major finding.
- Verify AS9102 Forms 1, 2, and 3 are complete and signed: all characteristics have ACTUAL recorded results (not restated requirements), pass/fail dispositions are indicated, special processes appear on Form 2 with their certificate numbers, serial/lot numbers are assigned where required, and any nonconformance carries an approved deviation (SEP) ticket number.
- Verify NADCAP claims: any accreditation scope cited on the forms must actually appear on the provided NADCAP certificate, and the certificate must not be expired relative to the work performed.
- Verify CoC minimum content (supplier, PO, part number/rev, lot/serial, quantity, specs, conformity statement, signature, date).
- Cross-check heat numbers, lot numbers, cert numbers, quantities, and dates across ALL documents; flag inconsistencies.
- For every finding, give the EXACT location (document name + page/sheet/form block) so a human reviewer can verify it.
- Mark the verdict UNAPPROVED if documentation is missing, incomplete, illegible, or inconsistent; if entries do not comply with drawings/specs/PO/revisions; or if deviations exist without prior Skyryse approval. Use NEEDS_INFO only when you cannot reach a verdict without an answer from the Skyryse engineer (not the supplier).
- Be precise and conservative: never invent document content. If a page is illegible, say so and list it as a finding.

SKYRYSE SUPPLIER QUALITY CLAUSES (flow-down requirements):
{clauses}
"""


def run_review(part_dir: Path, meta: dict) -> dict:
    """Convert all uploaded files for a part and run the Claude review."""
    uploads = sorted((part_dir / "uploads").glob("*"))
    if not uploads:
        raise ValueError("No files uploaded for this part")

    content: list[dict] = [{
        "type": "text",
        "text": (
            "Review the following FAIR documentation package for one part.\n"
            f"Part record created by the Skyryse reviewer: part number: {meta.get('part_number', 'unknown')}, "
            f"revision: {meta.get('revision', 'unknown')}, supplier: {meta.get('supplier', 'unknown')}, "
            f"PO: {meta.get('po_number', 'unknown')}.\n"
            f"Reviewer notes: {meta.get('notes') or 'none'}\n"
            "Scanned pages are provided as images — read them carefully, including handwritten "
            "annotations, stamps, and signatures. Some scans may be rotated."
        ),
    }]
    for f in uploads:
        content.extend(convert_file(f))

    client = anthropic.Anthropic()
    with client.messages.stream(
        model=MODEL,
        max_tokens=32000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": REVIEW_SCHEMA},
        },
        system=[{
            "type": "text",
            "text": _system_prompt(),
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": content}],
    ) as stream:
        message = stream.get_final_message()

    text = next(b.text for b in message.content if b.type == "text")
    review = json.loads(text)
    review["model"] = message.model
    review["usage"] = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "cache_read_input_tokens": message.usage.cache_read_input_tokens,
        "cache_creation_input_tokens": message.usage.cache_creation_input_tokens,
    }
    return review


METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "part_number": {"type": "string", "description": "Part number exactly as printed; empty string if not found anywhere in the package"},
        "part_name": {"type": "string", "description": "Part name / nomenclature / description from the drawing or FAIR Form 1; empty if not found"},
        "revision": {"type": "string", "description": "Part/drawing revision level; empty if not found"},
        "supplier": {"type": "string", "description": "Manufacturing supplier (the company that made/processed the part and signs the CoC); empty if not found"},
        "po_number": {"type": "string", "description": "Skyryse Purchase Order number; empty if not found"},
        "found_part_number": {"type": "boolean", "description": "True if a part number appears in the documents"},
        "found_supplier": {"type": "boolean"},
        "found_po_number": {"type": "boolean"},
        "discrepancy_note": {"type": "string", "description": "Note any inconsistency between documents for these fields, e.g. PO differs between CoC and packing slip; empty if consistent"},
    },
    "required": [
        "part_number", "part_name", "revision", "supplier", "po_number",
        "found_part_number", "found_supplier", "found_po_number", "discrepancy_note",
    ],
    "additionalProperties": False,
}


def extract_metadata(part_dir: Path) -> dict:
    """Read the package and pull identifying fields exactly as printed in the docs."""
    uploads = sorted((part_dir / "uploads").glob("*"))
    if not uploads:
        raise ValueError("No files uploaded for this part")

    content: list[dict] = [{
        "type": "text",
        "text": (
            "Read this supplier AS9102 FAIR documentation package and extract the identifying "
            "fields EXACTLY as they appear in the documents. Use the controlling drawing, FAIR "
            "Form 1, and the Certificate of Conformance as the authority. For part_name use the "
            "nomenclature/description on the drawing or Form 1. The supplier is the company that "
            "manufactured/processed the part and signs the CoC (not a distributor or the mill). "
            "If a field does not appear anywhere, return an empty string and set its found_* flag "
            "to false. Note in discrepancy_note if the same field shows different values across "
            "documents. Scanned pages are images — read them, including stamps and handwriting."
        ),
    }]
    for f in uploads:
        content.extend(convert_file(f))

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": METADATA_SCHEMA},
        },
        system="You extract identifying metadata from AS9102 FAIR packages. Report values exactly as printed in the documents; never guess.",
        messages=[{"role": "user", "content": content}],
    )
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text)


def review_to_markdown(review: dict, meta: dict) -> str:
    """Render the structured review as a human-readable markdown report."""
    lines = [
        f"# FAIR Review — {review.get('part_number')} — {review.get('part_name')}",
        "",
        f"**Verdict:** {review.get('verdict')}  |  **Supplier:** {review.get('supplier')}  |  **PO:** {review.get('po_number')}",
        "",
        "## Summary",
        review.get("summary", ""),
        "",
        f"## Traceability chain (complete: {'YES' if review.get('traceability_complete') else 'NO'})",
        "",
        "| Step | Entity | Document | Key IDs | Linked |",
        "|---|---|---|---|---|",
    ]
    for s in review.get("traceability_chain", []):
        lines.append(
            f"| {s['step']} | {s['entity']} | {s['document']} | {s['key_ids']} | {'✓' if s['linked'] else '✗ BROKEN'} |"
        )
    lines += ["", "## Findings", ""]
    for i, f in enumerate(review.get("findings", []), 1):
        lines += [
            f"### {i}. [{f['severity'].upper()}] {f['category']}",
            f"- **Issue:** {f['description']}",
            f"- **Where to verify:** {f['location']}",
            f"- **Required action:** {f['required_action']}",
            "",
        ]
    questions = review.get("clarifying_questions", [])
    if questions:
        lines += ["## Clarifying questions", ""]
        lines += [f"- {q}" for q in questions]
    return "\n".join(lines)
````

---

## app/jira_client.py

*Jira Cloud client — pull FAIR attachments from a ticket*

````python
"""Minimal Jira Cloud client — pull FAIR document attachments from a ticket.

Configured entirely via environment variables (no secrets in code):
    JIRA_BASE_URL    e.g. https://skyryse.atlassian.net
    JIRA_EMAIL       the Atlassian account email the API token belongs to
    JIRA_API_TOKEN   created at https://id.atlassian.com/manage-profile/security/api-tokens

Uses HTTP Basic auth (email:api_token) over HTTPS, the standard for Jira Cloud REST.
Dependency-free (urllib only).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class JiraError(Exception):
    pass


def is_configured() -> bool:
    return all(os.environ.get(k) for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"))


def _cfg() -> tuple[str, str]:
    base = (os.environ.get("JIRA_BASE_URL") or "").rstrip("/")
    email = os.environ.get("JIRA_EMAIL") or ""
    token = os.environ.get("JIRA_API_TOKEN") or ""
    if not (base and email and token):
        raise JiraError("Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN.")
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    return base, auth


def base_url() -> str:
    return (os.environ.get("JIRA_BASE_URL") or "").rstrip("/")


def _open(url: str, auth: str, accept: str = "application/json"):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "Accept": accept})
    return urllib.request.urlopen(req, timeout=90)


def get_issue(key: str) -> dict:
    """Return the issue with its attachment list and summary."""
    base, auth = _cfg()
    url = f"{base}/rest/api/3/issue/{key}?fields=attachment,summary,status"
    try:
        with _open(url, auth) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise JiraError(f"Issue '{key}' not found, or this account cannot see it.")
        if e.code in (401, 403):
            raise JiraError("Jira authentication/permission failed — check the email, API token, and that the account can view this ticket.")
        raise JiraError(f"Jira returned error {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise JiraError(f"Could not reach Jira ({base}): {e.reason}")


def list_attachments(key: str) -> tuple[str, list[dict]]:
    """Return (issue summary, [attachment dicts])."""
    data = get_issue(key)
    fields = data.get("fields", {}) or {}
    return fields.get("summary", "") or "", (fields.get("attachment") or [])


def download_attachments(key: str, dest_dir: Path, allowed_exts: set[str] | None = None) -> dict:
    """Download every (allowed) attachment on the issue into dest_dir.

    Returns {summary, saved:[names], skipped:[names]}.
    """
    base, auth = _cfg()
    summary, atts = list_attachments(key)
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved, skipped = [], []
    for a in atts:
        name = Path(a.get("filename", "")).name
        if not name:
            continue
        if allowed_exts is not None and Path(name).suffix.lower() not in allowed_exts:
            skipped.append(name)
            continue
        content_url = a.get("content")
        if not content_url:
            skipped.append(name)
            continue
        try:
            with _open(content_url, auth, accept="*/*") as r:
                (dest_dir / name).write_bytes(r.read())
            saved.append(name)
        except urllib.error.HTTPError as e:
            raise JiraError(f"Failed downloading '{name}' from {key}: {e.code} {e.reason}")
    return {"summary": summary, "saved": saved, "skipped": skipped}
````

---

## app/__init__.py

*Package marker*

````python

````

---

## app/static/index.html

*Single-page UI — branding, upload, dashboard, edit, verify, review*

````html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Skyryse · FAIR Review</title>
<style>
  :root {
    --ink:#0a0e14; --hero1:#33465f; --hero2:#0a0e14;
    --bg:#eef1f5; --card:#ffffff; --line:#e3e7ee; --muted:#6a7480;
    --accent:#3f8cff; --accent-d:#1f6fe0;
    --ok:#1a7f37; --bad:#c62828; --warn:#b26a00;
    --steel:#9fb0c3;
  }
  * { box-sizing:border-box; }
  body { margin:0; font-family:"Segoe UI",system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--ink); }
  a { color:var(--accent-d); }

  /* ---- brand / hero ---- */
  .hero { background:linear-gradient(160deg,var(--hero1) 0%,var(--hero2) 70%); color:#fff; padding:22px 32px 26px; }
  .brandrow { display:flex; align-items:center; gap:14px; }
  .logo-mark { width:34px; height:40px; flex:none; }
  .logo-mark path { fill:#ffffff; }
  .wordmark { font-weight:700; letter-spacing:5px; font-size:22px; }
  .wordmark .sky { color:var(--steel); }
  .wordmark .ryse { color:#fff; }
  .hero h1 { font-size:15px; font-weight:600; letter-spacing:1px; margin:16px 0 2px; text-transform:uppercase; color:#dce6f2; }
  .hero p { margin:0; color:#9fb0c3; font-size:13px; }

  main { max-width:1120px; margin:-14px auto 40px; padding:0 22px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:22px; margin-bottom:20px; box-shadow:0 1px 3px rgba(10,14,20,.05); }
  h2 { font-size:12px; margin:0 0 16px; text-transform:uppercase; letter-spacing:1px; color:var(--muted); }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; }
  label { font-size:11px; color:var(--muted); display:block; margin-bottom:5px; letter-spacing:.3px; }
  input[type=text], textarea { width:100%; padding:9px 11px; border:1px solid var(--line); border-radius:7px; font:inherit; background:#fbfcfe; }
  input[type=text]:focus, textarea:focus { outline:none; border-color:var(--accent); background:#fff; }
  textarea { resize:vertical; min-height:52px; }

  .drop { border:2px dashed var(--line); border-radius:10px; padding:24px; text-align:center; color:var(--muted); margin-top:14px; cursor:pointer; transition:.15s; }
  .drop.over { border-color:var(--accent); color:var(--accent-d); background:#f5f9ff; }
  .filelist { font-size:13px; margin:10px 0 0; padding-left:18px; }

  button { background:var(--accent); color:#fff; border:0; border-radius:7px; padding:10px 18px; font:inherit; font-weight:600; cursor:pointer; transition:.12s; }
  button:hover { background:var(--accent-d); }
  button.ghost { background:#eef2f7; color:var(--ink); }
  button.ghost:hover { background:#e2e8f1; }
  button.dark { background:var(--ink); }
  button.dark:hover { background:#1b2433; }
  button:disabled { opacity:.45; cursor:default; }
  .btnrow { display:flex; gap:10px; flex-wrap:wrap; margin-top:16px; }

  table { width:100%; border-collapse:collapse; font-size:14px; }
  th,td { text-align:left; padding:10px 11px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:var(--muted); }
  tr.clickable { cursor:pointer; }
  tr.clickable:hover { background:#f3f7fd; }

  .badge { display:inline-block; padding:3px 11px; border-radius:999px; font-size:12px; font-weight:700; letter-spacing:.3px; }
  .b-approved{background:#e3f3e7;color:var(--ok);} .b-unapproved{background:#fdebec;color:var(--bad);}
  .b-needs_info{background:#fdf3e3;color:var(--warn);} .b-reviewing{background:#e7efff;color:var(--accent-d);}
  .b-new{background:#eef1f5;color:var(--muted);} .b-error{background:#fdebec;color:var(--bad);} .b-reviewed{background:#e3f3e7;color:var(--ok);}

  .verdict-banner { padding:18px 22px; border-radius:10px; font-size:16px; font-weight:700; margin-bottom:18px; }
  .v-APPROVED{background:#e3f3e7;color:var(--ok);} .v-UNAPPROVED{background:#fdebec;color:var(--bad);} .v-NEEDS_INFO{background:#fdf3e3;color:var(--warn);}
  .summary { white-space:pre-wrap; line-height:1.6; }

  .finding { border:1px solid var(--line); border-left:4px solid var(--line); border-radius:8px; padding:13px 15px; margin-bottom:11px; }
  .finding.major{border-left-color:var(--bad);} .finding.minor{border-left-color:var(--warn);}
  .finding .loc{font-size:13px;color:var(--muted);margin-top:6px;} .finding .act{font-size:13px;margin-top:4px;}
  .sev{font-weight:800;font-size:11px;text-transform:uppercase;} .sev-major{color:var(--bad);} .sev-minor{color:var(--warn);} .sev-observation{color:var(--muted);}
  .broken{color:var(--bad);font-weight:700;}

  .topbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px;}
  .spinner{display:inline-block;width:14px;height:14px;border:2px solid #c6d4f5;border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;vertical-align:-2px;margin-right:6px;}
  @keyframes spin{to{transform:rotate(360deg);}}
  .muted{color:var(--muted);font-size:13px;} #detail{display:none;}
  .match-yes{color:var(--ok);font-weight:700;} .match-no{color:var(--bad);font-weight:700;} .match-na{color:var(--muted);}
  .verify-box{background:#f7faff;border:1px solid #dbe7fb;border-radius:9px;padding:14px 16px;margin-top:14px;}
  .qlist li{margin:6px 0;}
  .hint{font-size:12px;color:var(--muted);margin-top:4px;}
</style>
</head>
<body>

<div class="hero">
  <div class="brandrow">
    <svg class="logo-mark" viewBox="0 0 100 116" aria-hidden="true">
      <path d="M6 5 L33 5 L50 63 Z"/>
      <path d="M94 5 L67 5 L50 63 Z"/>
      <path d="M44 72 L56 72 L50 113 Z"/>
    </svg>
    <span class="wordmark"><span class="sky">SKY</span><span class="ryse">RYSE</span></span>
  </div>
  <h1>FAIR Review</h1>
  <p>AS9102 supplier documentation review — AI-assisted, engineer-approved</p>
</div>

<main>

  <section class="card" id="newPart">
    <h2>New FAIR Package</h2>
    <div class="grid">
      <div><label>Part number *</label><input type="text" id="f_pn" placeholder="1101021-01"></div>
      <div><label>Revision</label><input type="text" id="f_rev" placeholder="-"></div>
      <div><label>Part name</label><input type="text" id="f_name" placeholder="auto-filled from documents if blank"></div>
      <div><label>Supplier</label><input type="text" id="f_sup" placeholder="AH Machine Inc"></div>
      <div><label>PO number</label><input type="text" id="f_po" placeholder="3307"></div>
    </div>
    <div style="margin-top:12px"><label>Notes for the reviewer (optional)</label>
      <textarea id="f_notes" placeholder="e.g. drawing attached; supplier claims delta FAIR"></textarea>
    </div>
    <div class="drop" id="drop">Drop supplier documents here or click to browse<br>
      <span class="muted">PDF, Excel, Word, images — scanned certs are fine</span>
      <input type="file" id="fileInput" multiple hidden>
    </div>
    <ul class="filelist" id="pendingFiles"></ul>
    <div class="btnrow">
      <button id="btnCreate">Upload package</button>
      <button id="btnCreateReview" class="dark">Upload &amp; start review</button>
    </div>
    <div class="hint" id="createMsg"></div>
  </section>

  <section class="card">
    <div class="topbar"><h2 style="margin:0">Parts</h2>
      <button class="ghost" onclick="loadParts()">Refresh</button></div>
    <table>
      <thead><tr><th>Part #</th><th>Name</th><th>Supplier</th><th>PO</th><th>Docs</th><th>Status</th><th>Verdict</th></tr></thead>
      <tbody id="partsBody"></tbody>
    </table>
  </section>

  <section class="card" id="detail">
    <div class="topbar">
      <h2 style="margin:0" id="d_title">Part</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button id="btnReview">Run review</button>
        <a id="btnReport" href="#" style="display:none"><button class="ghost">Download report (.md)</button></a>
        <button class="ghost" onclick="hideDetail()">Close</button>
      </div>
    </div>
    <div id="d_status" class="muted" style="margin-bottom:14px"></div>

    <h2>Part details (editable)</h2>
    <div class="grid">
      <div><label>Part number *</label><input type="text" id="e_pn"></div>
      <div><label>Revision</label><input type="text" id="e_rev"></div>
      <div><label>Part name</label><input type="text" id="e_name"></div>
      <div><label>Supplier</label><input type="text" id="e_sup"></div>
      <div><label>PO number</label><input type="text" id="e_po"></div>
    </div>
    <div style="margin-top:12px"><label>Notes</label><textarea id="e_notes"></textarea></div>
    <div class="btnrow">
      <button id="btnSave">Save changes</button>
      <button id="btnVerify" class="ghost">Verify against documents</button>
    </div>
    <div class="hint" id="editMsg"></div>
    <div id="verifyPanel"></div>

    <div id="d_files" class="muted" style="margin:16px 0 4px"></div>
    <div id="d_review"></div>
  </section>

</main>
<script>
let pending = [], currentId = null, pollTimer = null;
const $ = (id) => document.getElementById(id);
const esc = (s) => { const d=document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };
const norm = (s) => (s ?? "").toString().toLowerCase().replace(/[\s\-_.]/g,"").trim();

/* ---------- upload form ---------- */
const drop=$("drop"), fileInput=$("fileInput");
drop.onclick=()=>fileInput.click();
drop.ondragover=(e)=>{e.preventDefault();drop.classList.add("over");};
drop.ondragleave=()=>drop.classList.remove("over");
drop.ondrop=(e)=>{e.preventDefault();drop.classList.remove("over");addFiles(e.dataTransfer.files);};
fileInput.onchange=()=>addFiles(fileInput.files);
function addFiles(list){ for(const f of list) pending.push(f);
  $("pendingFiles").innerHTML = pending.map(f=>`<li>${esc(f.name)} <span class="muted">(${(f.size/1024).toFixed(0)} KB)</span></li>`).join(""); }

async function createPart(startReview){
  const pn=$("f_pn").value.trim();
  if(!pn){ $("createMsg").textContent="Part number is required."; return; }
  const fd=new FormData();
  fd.append("part_number",pn); fd.append("revision",$("f_rev").value);
  fd.append("part_name",$("f_name").value); fd.append("supplier",$("f_sup").value);
  fd.append("po_number",$("f_po").value); fd.append("notes",$("f_notes").value);
  for(const f of pending) fd.append("files",f);
  $("createMsg").innerHTML='<span class="spinner"></span>Uploading…';
  const res=await fetch("/api/parts",{method:"POST",body:fd});
  if(!res.ok){ $("createMsg").textContent="Error: "+(await res.json()).detail; return; }
  const data=await res.json();
  $("createMsg").textContent=`Saved ${data.saved_files.length} file(s) for ${data.id}.`;
  pending=[]; $("pendingFiles").innerHTML=""; fileInput.value="";
  ["f_pn","f_rev","f_name","f_sup","f_po","f_notes"].forEach(i=>$(i).value="");
  if(startReview) await fetch(`/api/parts/${data.id}/review`,{method:"POST"});
  await loadParts(); openDetail(data.id);
}
$("btnCreate").onclick=()=>createPart(false);
$("btnCreateReview").onclick=()=>createPart(true);

/* ---------- parts list ---------- */
async function loadParts(){
  const parts=await(await fetch("/api/parts")).json();
  $("partsBody").innerHTML = parts.map(p=>`
    <tr class="clickable" onclick="openDetail('${p.id}')">
      <td><strong>${esc(p.part_number)}</strong>${p.revision?` <span class="muted">${esc(p.revision)}</span>`:""}</td>
      <td>${esc(p.part_name)}</td><td>${esc(p.supplier)}</td><td>${esc(p.po_number)}</td>
      <td>${p.file_count}</td><td>${statusBadge(p.status)}</td>
      <td>${p.verdict?verdictBadge(p.verdict):""}</td>
    </tr>`).join("") || '<tr><td colspan="7" class="muted">No parts yet — upload your first FAIR package above.</td></tr>';
}
const statusBadge=(s)=>`<span class="badge b-${s}">${s==="reviewing"?'<span class="spinner"></span>reviewing':s}</span>`;
const verdictBadge=(v)=>`<span class="badge b-${v.toLowerCase()}">${v.replace("_"," ")}</span>`;

/* ---------- detail ---------- */
async function openDetail(id){ currentId=id; $("detail").style.display="block"; await refreshDetail(); $("detail").scrollIntoView({behavior:"smooth"}); }
function hideDetail(){ $("detail").style.display="none"; currentId=null; if(pollTimer){clearTimeout(pollTimer);pollTimer=null;} }

let lastMeta=null;
async function refreshDetail(){
  if(!currentId) return;
  const {meta,review}=await(await fetch(`/api/parts/${currentId}`)).json();
  lastMeta=meta;
  $("d_title").textContent=`${meta.part_number} ${meta.revision?"Rev "+meta.revision:""}${meta.part_name?" — "+meta.part_name:""}`;
  $("d_status").innerHTML=`Status: ${statusBadge(meta.status)}`+(meta.error?` <span class="broken">${esc(meta.error)}</span>`:"");

  // editable fields (don't clobber while user is typing mid-edit unless first load of this part)
  if($("e_pn").dataset.part!==meta.id){
    $("e_pn").value=meta.part_number||""; $("e_rev").value=meta.revision||"";
    $("e_name").value=meta.part_name||""; $("e_sup").value=meta.supplier||"";
    $("e_po").value=meta.po_number||""; $("e_notes").value=meta.notes||"";
    $("e_pn").dataset.part=meta.id;
  }

  $("btnReview").disabled=meta.status==="reviewing";
  $("btnReview").textContent=meta.status==="reviewed"?"Re-run review":"Run review";
  $("btnVerify").disabled=!!meta.verifying;
  $("btnVerify").innerHTML=meta.verifying?'<span class="spinner"></span>Reading documents…':"Verify against documents";
  $("btnReport").style.display=review?"inline":"none";
  $("btnReport").href=`/api/parts/${meta.id}/report.md`;

  renderVerify(meta);
  $("d_files").innerHTML="Documents: "+(meta.files||[]).map(f=>`<a href="/api/parts/${meta.id}/files/${encodeURIComponent(f)}" target="_blank">${esc(f)}</a>`).join(" · ");
  $("d_review").innerHTML=review?renderReview(review):(meta.status==="reviewing"?'<div class="muted"><span class="spinner"></span>Claude is reviewing the package — typically 1–3 minutes…</div>':"");

  if(meta.status==="reviewing"||meta.verifying){ pollTimer=setTimeout(refreshDetail,4000); loadParts(); }
  else if(pollTimer){ clearTimeout(pollTimer); pollTimer=null; loadParts(); }
}

/* ---------- save edits ---------- */
$("btnSave").onclick=async()=>{
  const fd=new FormData();
  fd.append("part_number",$("e_pn").value); fd.append("revision",$("e_rev").value);
  fd.append("part_name",$("e_name").value); fd.append("supplier",$("e_sup").value);
  fd.append("po_number",$("e_po").value); fd.append("notes",$("e_notes").value);
  $("editMsg").innerHTML='<span class="spinner"></span>Saving…';
  const res=await fetch(`/api/parts/${currentId}/edit`,{method:"POST",body:fd});
  if(!res.ok){ $("editMsg").textContent="Error: "+(await res.json()).detail; return; }
  const data=await res.json();
  $("editMsg").textContent="Saved.";
  $("e_pn").dataset.part="";           // force re-sync of fields
  currentId=data.id;                   // id may have changed if part # changed
  await refreshDetail(); loadParts();
};

/* ---------- verify against documents ---------- */
$("btnVerify").onclick=async()=>{
  $("editMsg").textContent="";
  const res=await fetch(`/api/parts/${currentId}/verify`,{method:"POST"});
  if(!res.ok){ alert((await res.json()).detail); return; }
  refreshDetail();
};

function renderVerify(meta){
  const ex=meta.extracted;
  if(meta.verify_error){ $("verifyPanel").innerHTML=`<div class="verify-box"><span class="broken">Verification failed: ${esc(meta.verify_error)}</span></div>`; return; }
  if(!ex){ $("verifyPanel").innerHTML=""; return; }
  const rows=[
    ["Part number", meta.part_number, ex.part_number, ex.found_part_number],
    ["Part name",   meta.part_name,   ex.part_name,   !!ex.part_name],
    ["Revision",    meta.revision,    ex.revision,    !!ex.revision],
    ["Supplier",    meta.supplier,    ex.supplier,    ex.found_supplier],
    ["PO number",   meta.po_number,   ex.po_number,   ex.found_po_number],
  ];
  let html=`<div class="verify-box"><strong>Read from the documents</strong> — compare what you entered against what the package actually shows:
    <table style="margin-top:10px"><thead><tr><th>Field</th><th>You entered</th><th>Found in documents</th><th>Check</th></tr></thead><tbody>`;
  for(const [label,entered,found,present] of rows){
    let mark;
    if(!present||!found){ mark=`<span class="match-no">✗ not found</span>`; }
    else if(!entered){ mark=`<span class="match-na">— (blank)</span>`; }
    else if(norm(entered)===norm(found)){ mark=`<span class="match-yes">✓ match</span>`; }
    else { mark=`<span class="match-no">✗ differs</span>`; }
    html+=`<tr><td>${label}</td><td>${esc(entered)||'<span class="muted">—</span>'}</td><td>${esc(found)||'<span class="muted">—</span>'}</td><td>${mark}</td></tr>`;
  }
  html+="</tbody></table>";
  if(ex.discrepancy_note) html+=`<div class="hint" style="margin-top:8px">⚠ ${esc(ex.discrepancy_note)}</div>`;
  html+=`<div class="btnrow"><button class="ghost" onclick="useDocValues()">Use document values</button></div></div>`;
  $("verifyPanel").innerHTML=html;
}
function useDocValues(){
  const ex=lastMeta&&lastMeta.extracted; if(!ex) return;
  if(ex.part_number) $("e_pn").value=ex.part_number;
  if(ex.part_name) $("e_name").value=ex.part_name;
  if(ex.revision) $("e_rev").value=ex.revision;
  if(ex.supplier) $("e_sup").value=ex.supplier;
  if(ex.po_number) $("e_po").value=ex.po_number;
  $("editMsg").textContent='Document values filled in — review them and click "Save changes".';
}

/* ---------- review rendering ---------- */
$("btnReview").onclick=async()=>{
  const res=await fetch(`/api/parts/${currentId}/review`,{method:"POST"});
  if(!res.ok) alert((await res.json()).detail);
  refreshDetail();
};
function renderReview(r){
  let html=`<h2 style="margin-top:8px">Review result</h2><div class="verdict-banner v-${r.verdict}">Verdict: ${r.verdict.replace("_"," ")}
    &nbsp;—&nbsp; traceability ${r.traceability_complete?"COMPLETE":"INCOMPLETE"}</div>`;
  html+=`<div class="summary">${esc(r.summary)}</div>`;
  html+=`<h2 style="margin-top:20px">Traceability chain</h2><table><thead><tr><th>Step</th><th>Entity</th><th>Evidence</th><th>Key IDs</th><th>Link</th></tr></thead><tbody>`;
  for(const s of r.traceability_chain||[]) html+=`<tr><td>${esc(s.step)}</td><td>${esc(s.entity)}</td><td>${esc(s.document)}</td><td>${esc(s.key_ids)}</td><td>${s.linked?"✓":'<span class="broken">✗ BROKEN</span>'}</td></tr>`;
  html+=`</tbody></table>`;
  html+=`<h2 style="margin-top:20px">Findings (${(r.findings||[]).length})</h2>`;
  for(const f of r.findings||[]) html+=`<div class="finding ${f.severity}"><span class="sev sev-${f.severity}">${f.severity}</span> · <strong>${esc(f.category)}</strong>
      <div style="margin-top:4px">${esc(f.description)}</div><div class="loc">📍 ${esc(f.location)}</div><div class="act">➜ ${esc(f.required_action)}</div></div>`;
  if((r.clarifying_questions||[]).length) html+=`<h2 style="margin-top:20px">Clarifying questions</h2><ul class="qlist">`+r.clarifying_questions.map(q=>`<li>${esc(q)}</li>`).join("")+"</ul>";
  if(r.usage) html+=`<div class="muted" style="margin-top:16px">Model: ${esc(r.model||"")} · tokens in/out: ${r.usage.input_tokens}/${r.usage.output_tokens} (cache read: ${r.usage.cache_read_input_tokens})</div>`;
  return html;
}

loadParts();
</script>
</body>
</html>
````

---

## requirements.txt

*Python dependencies*

````text
fastapi
uvicorn[standard]
anthropic
python-multipart
pdfplumber
pypdfium2
pandas
xlrd
openpyxl
python-docx
pillow
````

---

## run_secure.ps1

*Localhost launcher (loads API key, binds 127.0.0.1)*

````powershell
# Launch the FAIR Review app for a single-machine pilot.
# Binds to 127.0.0.1 so ONLY this machine can reach it (no network exposure),
# and loads the API key from your User environment variable.
#
# Usage:  right-click -> Run with PowerShell, or:  .\run_secure.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$key = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
if ([string]::IsNullOrWhiteSpace($key) -or $key.Length -lt 40) {
    Write-Host "ANTHROPIC_API_KEY is not set (or looks invalid) for your user account." -ForegroundColor Red
    Write-Host "Set it once with:  [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY','sk-ant-...','User')"
    exit 1
}
$env:ANTHROPIC_API_KEY = $key

Write-Host "Starting FAIR Review at http://127.0.0.1:8000  (this machine only)" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
````

---

## Start FAIR Review.bat

*Double-click launcher (bypasses script policy)*

````bat
@echo off
title FAIR Review Server - keep this window open
cd /d "%~dp0"
echo ================================================================
echo   Skyryse FAIR Review
echo   Starting the server. Keep this window OPEN while you work.
echo   When you are done, close this window or press Ctrl+C.
echo ----------------------------------------------------------------
echo   Then open your browser to:  http://127.0.0.1:8000
echo ================================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_secure.ps1"
echo.
echo Server stopped. You can close this window.
pause
````

---

## tools/extract_pdf.py

*Utility: PDF text -> markdown*

````python
"""Extract text from a PDF into a markdown file, page by page."""
import sys
import pdfplumber

src, out = sys.argv[1], sys.argv[2]

with pdfplumber.open(src) as pdf:
    print(f"Pages: {len(pdf.pages)}")
    parts = []
    for i, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or "[NO TEXT - possibly scanned image]"
        parts.append(f"<!-- Page {i} -->\n{text}")

with open(out, "w", encoding="utf-8") as f:
    f.write("\n\n".join(parts))

print("Written:", out)
````

---

## tools/extract_xls.py

*Utility: Excel workbook -> markdown*

````python
"""Dump every sheet of an Excel workbook (.xls/.xlsx) to a markdown file."""
import sys
import pandas as pd

src, out = sys.argv[1], sys.argv[2]

sheets = pd.read_excel(src, sheet_name=None, header=None, dtype=str)
parts = []
for name, df in sheets.items():
    df = df.fillna("")
    lines = [f"## Sheet: {name}"]
    for idx, row in df.iterrows():
        cells = [str(c).strip() for c in row.tolist()]
        if any(cells):
            # row number (1-based, as in Excel) then non-empty cells with column letters
            rendered = " | ".join(
                f"[{chr(65 + i) if i < 26 else 'A' + chr(65 + i - 26)}] {c}"
                for i, c in enumerate(cells) if c
            )
            lines.append(f"Row {idx + 1}: {rendered}")
    parts.append("\n".join(lines))

with open(out, "w", encoding="utf-8") as f:
    f.write("\n\n".join(parts))

print("Sheets:", ", ".join(sheets.keys()))
print("Written:", out)
````

---

## tools/pdf_to_png.py

*Utility: render scanned PDF pages to PNG*

````python
"""Render each page of a PDF to PNG images for visual reading of scanned docs."""
import sys
import os
import pypdfium2 as pdfium

src, outdir, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
scale = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0  # ~144 DPI

os.makedirs(outdir, exist_ok=True)
pdf = pdfium.PdfDocument(src)
for i, page in enumerate(pdf, 1):
    bitmap = page.render(scale=scale)
    img = bitmap.to_pil()
    path = os.path.join(outdir, f"{prefix}_p{i:02d}.png")
    img.save(path)
    print(path)
````

---

## tools/backup.py

*Rotating ZIP backup of all records*

````python
"""Timestamped, rotating backup of all FAIR review data.

Copies the parts/ tree, the quality clauses, and the audit log into a dated
ZIP under the backup directory, then prunes old backups beyond KEEP_COUNT.

Run manually:   python tools/backup.py
Or on a schedule (see tools/install_backup_task.ps1).

By default backups go to a `Backups` folder NEXT TO the project. For real
durability, point BACKUP_DIR at a second physical disk or a company-approved
backup location (set the FAIR_BACKUP_DIR environment variable).
"""
from __future__ import annotations

import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_DIR = ROOT.parent / "FAIR_Backups"
BACKUP_DIR = Path(os.environ.get("FAIR_BACKUP_DIR", str(DEFAULT_BACKUP_DIR)))
KEEP_COUNT = 30  # keep the most recent N backups

INCLUDE = ["parts", "Skyryse Quality Clauses.md", "audit.log"]


def make_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    dest = BACKUP_DIR / f"fair_backup_{stamp}.zip"

    file_count = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in INCLUDE:
            path = ROOT / item
            if path.is_file():
                zf.write(path, path.name)
                file_count += 1
            elif path.is_dir():
                for f in path.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(ROOT))
                        file_count += 1
    return dest, file_count


def prune() -> int:
    backups = sorted(BACKUP_DIR.glob("fair_backup_*.zip"))
    removed = 0
    while len(backups) > KEEP_COUNT:
        old = backups.pop(0)
        old.unlink()
        removed += 1
    return removed


if __name__ == "__main__":
    dest, n = make_backup()
    removed = prune()
    size_kb = dest.stat().st_size / 1024
    print(f"Backed up {n} files -> {dest} ({size_kb:.0f} KB)")
    if removed:
        print(f"Pruned {removed} old backup(s); keeping last {KEEP_COUNT}.")
````
