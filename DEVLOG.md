# Skyryse FAIR Review — Dev Handoff

**Repo:** https://github.com/abelnapoleon-sky/skyryse-fair-review  
**Local path:** `C:\Users\AbelNapoleon\OneDrive - skyryse.com\Documents\skyryse-fair-review`  
**Stack:** Python 3, FastAPI, uvicorn, Anthropic API (`claude-sonnet-4-6`), pdfplumber, pypdfium2, python-docx

---

## What this app does

AI-powered FAIR document review tool for Skyryse's supplier quality workflow. An engineer uploads a supplier's FAIR package (PDFs, Excel, scanned certs), the app reads the documents, auto-fills part metadata, and runs a structured AS9102 review via Claude. Results are stored as JSON and a markdown report per part. No database — everything lives as files under `parts/<part-id>/`.

---

## Current file structure

```
skyryse-fair-review/
├── app/
│   ├── server.py          — FastAPI routes (all endpoints)
│   ├── pipeline.py        — Claude API calls (extract metadata + run review)
│   ├── jira_client.py     — Jira Cloud attachment downloader
│   ├── static/
│   │   └── index.html     — Single-page UI
│   └── __init__.py
├── tools/
│   └── backup.py          — Rotating ZIP backup of parts/ folder (not yet scheduled)
├── parts/                 — Runtime data, gitignored
├── PROJECT_INSTRUCTIONS.md — Full review spec (prompt reference, not yet wired in)
├── REQUIREMENTS_AND_BUILD.md
├── COST_ANALYSIS.md
├── SOURCE_CODE.md         — Snapshot of full source at a point in time
└── Start FAIR Review.bat  — Windows launcher (calls run_secure.ps1, gitignored)
```

---

## Everything built/changed in this session

### 1. SEP# field (server.py, index.html)
Added `sep_number` as a first-class field across the whole stack:
- `create_part` and `edit_part` form endpoints both accept it
- Stored in `part.json` metadata
- Surfaced in the parts list API response
- New "FAIR Submission SEP#" input on the new-part form and edit form
- New SEP# column in the parts table

### 2. Jira attachment pull (jira_client.py, server.py, index.html)
`app/jira_client.py` was already written but orphaned (not wired in). Fully connected it:
- New `POST /api/parts/from-jira` endpoint
- Configured via 3 env vars (see below) — no secrets in code
- Filters attachments by allowed extensions (PDF, XLS, XLSX, PNG, JPG, etc.)
- "Pull from Jira" input box on the UI, pre-filled with SEP-# format placeholder
- Graceful "not configured" error if env vars aren't set

### 3. Fully automatic metadata extraction after Jira pull (server.py)
After downloading attachments from Jira, the server immediately:
1. Calls `pipeline.extract_metadata()` on the downloaded files
2. Applies whatever fields were found (part_number, revision, supplier, po_number) directly to the record — no "click to apply" step
3. Renames the record from the SEP key to the real part number if one is found (e.g. `parts/SEP-331/` → `parts/1005058-01/`)
4. Falls back gracefully: if extraction fails (bad key, network error), files are still saved and the record stays under the SEP key with the error logged

### 4. Model switch (pipeline.py)
Changed `MODEL` constant from `claude-opus-4-8` to `claude-sonnet-4-6` for higher throughput and lower cost per token.

### 5. PROJECT_INSTRUCTIONS.md added to repo root
Full review spec saved as reference — covers pre-screen workflow, efficiency review, full review, HTML report format, quality clause library, Nadcap/supplier knowledge. **Not yet wired into pipeline.py** — the app still runs the original JSON-schema review and produces a markdown report. Wiring this in is a future task (see below).

---

## Environment variables required

Set these before starting the server. For local dev use `$env:VAR = "value"` in PowerShell. For the EC2 deployment set them as persistent system environment variables so the NSSM Windows Service sees them on restart.

| Variable | Value | Required |
|---|---|---|
| `ANTHROPIC_API_KEY` | From console.anthropic.com/settings/keys | Yes |
| `JIRA_BASE_URL` | `https://skyryse.atlassian.net` | For Jira pull only |
| `JIRA_EMAIL` | `abel.napoleon@skyryse.com` | For Jira pull only |
| `JIRA_API_TOKEN` | Generate at id.atlassian.com → Security → API tokens | For Jira pull only |

---

## How to run locally

```powershell
cd "C:\Users\AbelNapoleon\OneDrive - skyryse.com\Documents\skyryse-fair-review"
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:JIRA_BASE_URL = "https://skyryse.atlassian.net"
$env:JIRA_EMAIL = "abel.napoleon@skyryse.com"
$env:JIRA_API_TOKEN = "your-token"
python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

Dependencies (no requirements.txt yet — install manually):
```
pip install fastapi uvicorn anthropic pandas pdfplumber pypdfium2 python-docx openpyxl python-multipart
```

---

## Current known issue: Anthropic rate limit (429)

**Problem:** The org API account is on Tier 1, capped at 10,000 input tokens/minute. Scanned FAIR packages (especially multi-page image PDFs) exceed this in a single request. Both `claude-opus-4-8` and `claude-sonnet-4-6` hit the same cap since it's org-level, not model-level.

**Immediate fix:** Request a rate limit increase at console.anthropic.com/settings/limits, or contact Anthropic sales via the link in the error message. This is the real fix.

**Stopgap option (not yet implemented):** Lower the DPI used when rendering scanned PDF pages to images in `pipeline.py`. Cuts input token count at the cost of slightly less legible images for tiny cert text. Worth doing once the rate limit situation is clearer.

---

## EC2 deployment plan (in progress)

- Instance: Windows, existing box set up for Robert
- DNS: `skyryse-fair-review.skyryse.io` (IT to configure via ALB)
- Remote access: IT to add the server to `remote.skyryse.io`
- Service wrapper: NSSM (Non-Sucking Service Manager) to run uvicorn as a Windows Service that survives reboots and logouts
- No separate DB needed — `parts/` folder lives on the instance's EBS volume
- Backups: `tools/backup.py` exists but needs a Windows Task Scheduler job to actually run it
- EAR/ECCN note: documents handled by this app may be controlled. Confirm with IT whether the EBS volume is included in standard EC2 snapshot policy

---

## Outstanding tasks / next steps

1. **Rate limit** — request increase at console.anthropic.com before going to EC2
2. **Wire in PROJECT_INSTRUCTIONS.md** — rewrite `pipeline.py` system prompt to match the full spec (pre-screen → efficiency → full review), switch output from JSON + markdown to single styled HTML file per the spec's CSS, update `server.py` routes and UI accordingly
3. **Add requirements.txt** to repo so dependencies are explicit
4. **Stamp Control integration** — `Code.gs` / `Index.html` (Google Apps Script stamp tracker) was shared but the integration scope wasn't fully defined. Revisit once the FAIR Review tool is stable
5. **NSSM Windows Service setup** on EC2 once IT provisions access
6. **Schedule backup job** via Windows Task Scheduler pointing at `tools/backup.py`
7. **Test Jira pull end-to-end** on a real SEP ticket once the Jira API token is generated and env vars are set on the running server

---

## Key discrepancy found during testing (SEP-331, 1005058-01)

The "Verify against documents" step flagged a real quality issue in the test package:
- `SEP_331_1005058_PL_COC.pdf` shows Part/Drawing # as `100505 REV A`, Qty 5 — this appears to be an earlier development shipment CoC mixed into the REV C flight package
- The delivery note `54672` correctly shows `1005058-01 REV C`, Qty 30, PO 2332
- The FAIR Form 1 reviewed copy also lists Supplier Code SEP-331
- **Action needed:** Rubbertech needs to provide the correct REV C CoC before this package can be accepted

Also for SEP-292 (1005033-01 PIN SPRING - YAW):
- Cardinal Precision CoC and packing slip show Revision D
- FAIR Form 1 and controlling drawing reference Revision E (drawing is actually Rev F)
- Supplier CoC revision doesn't match the FAIR Form 1 revision — needs resolution
