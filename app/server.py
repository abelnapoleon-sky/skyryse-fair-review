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
