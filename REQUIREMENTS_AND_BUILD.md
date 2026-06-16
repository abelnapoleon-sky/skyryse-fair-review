# FAIR Review Tool — Requirements & Build Reference

**Owner:** Abel Napoleon, Supplier Quality
**Date:** June 12, 2026
**Status:** Working single-machine pilot; multi-user AWS deployment planned.

This document captures (1) what the tool is required to do and (2) the code/components that implement it, so the build can be understood, maintained, or handed to IT for the production version.

---

## 1. Purpose

Help Supplier Quality engineers review supplier **AS9102 First Article Inspection Report (FAIR)** packages. The engineer provides a supplier's documentation; the tool reads it and produces a **draft** review of completeness, accuracy, and traceability against the Skyryse Supplier Quality Clauses and AS9102. A human engineer makes the final acceptance decision — the AI output is decision-support.

---

## 2. Functional Requirements

| # | Requirement |
|---|---|
| F1 | Accept a FAIR package as uploaded files (PDF, Excel, Word, images), including **scanned** documents. |
| F2 | Read scanned/image documents directly (no separate OCR step), including stamps and handwriting. |
| F3 | Read the supplier package and produce a structured review: **verdict** (Approved / Unapproved / Needs Info), **traceability chain** (mill/OEM → Skyryse, with broken links flagged), **findings** (severity + exact document/page location + required action), and **clarifying questions**. |
| F4 | Treat the Skyryse Supplier Quality Clauses as flow-down requirements alongside AS9102 in every review. |
| F5 | Capture and edit part metadata: **Part #, Revision, Part Name, Supplier, PO #, Notes**. |
| F6 | **Verify against documents:** read the package and confirm the entered Part #, PO, and Supplier actually appear, and auto-extract the Part Name. Flag mismatches and cross-document inconsistencies. |
| F7 | Maintain a record per part: original documents, metadata, the review result, and a downloadable report. |
| F8 | Provide a dashboard listing all parts with status and verdict. |
| F9 | Keep an **audit trail** of every create / upload / edit / review action (who, when, what). |
| F10 | **Import documents directly from Jira** by ticket key (FAIR documents are attachments on SEP/Service-Desk tickets). *(Integration built; pending Jira credentials to activate.)* |

## 3. Non-Functional Requirements

| # | Requirement |
|---|---|
| N1 | **Export control:** the data includes EAR/ECCN-controlled technical data. Storage and transmission must stay within approved boundaries; production target is **AWS GovCloud** with AI inference via **Amazon Bedrock**. |
| N2 | **Security:** no secrets in code (env vars / Secrets Manager); audit trail retained; access restricted (pilot = localhost + Windows account; production = corporate SSO). |
| N3 | **Durability:** automated, rotating backups of all records. |
| N4 | **Reliability over scale:** sized for 3–4 engineers and low volume; correctness and traceability matter more than throughput. |
| N5 | **Human-in-the-loop:** the tool never auto-accepts a FAIR; it produces a draft for engineer sign-off. |

## 4. System Architecture (pilot)

```
Browser (engineer)
   │  http://127.0.0.1:8000  (localhost only)
   ▼
FastAPI app  (app/server.py)
   ├─ Conversion + AI review pipeline  (app/pipeline.py)
   │     ├─ PDF/Excel/Word/image → Claude-readable content
   │     └─ Claude Opus 4.8 → structured JSON review
   ├─ Jira import  (app/jira_client.py)        [pending credentials]
   ├─ Local storage  parts/<part>/             (documents, metadata, review)
   └─ Audit log  audit.log
```

## 5. Code & Components

| File | Responsibility |
|---|---|
| `app/server.py` | FastAPI web server. Endpoints for parts CRUD, file upload, edit, verify, review jobs, Jira import, report/file download. Writes the audit log. Background threads run reviews/verifications and the UI polls for status. |
| `app/pipeline.py` | Document conversion + AI calls. `convert_file()` turns each upload into Claude content blocks (text-native pages → text; scanned pages → page images). `run_review()` makes the structured review call; `extract_metadata()` is the lighter "verify against documents" call. Holds the system prompt (QE role + quality clauses) and the JSON schemas that constrain the output. |
| `app/jira_client.py` | Pulls attachments from a Jira Cloud ticket via REST (Basic auth from env vars). Dependency-free. |
| `app/static/index.html` | Single-page UI — Skyryse branding, upload form, parts dashboard, editable detail view, verify panel, review rendering. |
| `tools/extract_pdf.py`, `extract_xls.py`, `pdf_to_png.py` | Standalone conversion utilities (used for manual reviews / debugging). |
| `tools/backup.py` | Rotating ZIP backup of `parts/`, the clauses, and the audit log. |
| `run_secure.ps1`, `Start FAIR Review.bat` | Launchers that load the API key and bind the app to localhost. |
| `Skyryse Quality Clauses.md` | The flow-down requirements baseline loaded into every review. |

## 6. Data Model & Storage

Each part is a folder `parts/<part-id>/`:

| Item | Contents |
|---|---|
| `uploads/` | The original supplier documents |
| `part.json` | Metadata: id, part_number, revision, part_name, supplier, po_number, notes, status, verdict, timestamps, extracted-from-documents values |
| `review.json` | The structured review result + token usage |
| `REVIEW_<part>.md` | Human-readable report (downloadable) |
| `audit.log` (project root) | Append-only JSON-lines audit trail |

## 7. Processing Pipeline

1. **Convert** — each file → Claude content. Text-layer PDF pages become text; scanned pages render to images; Excel becomes per-sheet structured text; Word becomes text.
2. **Review** — one Claude Opus 4.8 call. System prompt = QE role + Skyryse Quality Clauses (cached). User content = the whole converted package. Output is constrained to a JSON schema (verdict, traceability chain, findings, questions).
3. **Render & store** — JSON saved; markdown report generated; status + verdict written to `part.json`; action recorded in the audit log.

The optional **verify** step runs a lighter version of step 2 that returns only the identifying fields (Part #, Name, Rev, Supplier, PO) exactly as printed, plus found/discrepancy flags.

## 8. API Endpoints

| Method & path | Purpose |
|---|---|
| `GET /api/parts` | List all parts |
| `POST /api/parts` | Create a part + upload documents |
| `POST /api/parts/{id}/files` | Add documents to a part |
| `POST /api/parts/{id}/edit` | Edit metadata (renames record if part # changes) |
| `POST /api/parts/{id}/verify` | Read documents to confirm/auto-fill metadata |
| `POST /api/parts/{id}/review` | Run the full AI review (background) |
| `GET /api/parts/{id}` | Get a part's metadata + review |
| `GET /api/parts/{id}/files/{name}` | Download an original document |
| `GET /api/parts/{id}/report.md` | Download the review report |
| `POST /api/parts/from-jira` | Create a part by pulling a Jira ticket's attachments *(pending activation)* |

## 9. Jira Integration

FAIR documents are attachments on Skyryse Jira / Supplier Exchange Portal (SEP) tickets. `app/jira_client.py` pulls them by ticket key using the Jira Cloud REST API with Basic auth.

**To activate, set three environment variables (no secrets in code):**
- `JIRA_BASE_URL` — e.g. `https://skyryse.atlassian.net`
- `JIRA_EMAIL` — the Atlassian account email
- `JIRA_API_TOKEN` — created at id.atlassian.com → Security → API tokens

The account needs read access to the SEP tickets and their attachments. Once set, an engineer enters a ticket key and the tool downloads the package, then "Verify against documents" auto-fills the metadata.

## 10. Build & Run (pilot)

1. `pip install -r requirements.txt`
2. Set `ANTHROPIC_API_KEY` (and, for Jira, the three `JIRA_*` vars) as user environment variables.
3. Launch with `Start FAIR Review.bat` (or `run_secure.ps1`).
4. Open `http://127.0.0.1:8000`.

## 11. Roadmap — Production (multi-user)

Detailed in the System Requirements document. Summary of work:

| Area | Pilot | Production |
|---|---|---|
| Hosting | One workstation | AWS GovCloud (Fargate) |
| Storage | Local files | S3 (documents) + Aurora PostgreSQL (records) |
| AI inference | Anthropic API | Claude via Amazon Bedrock (in-boundary) |
| Auth | Windows account | Corporate SSO / Cognito + MFA |
| Secrets | Env vars | AWS Secrets Manager |
| Access | localhost | Internal, behind VPN |

The application code is structured so the storage and inference layers can be swapped for their AWS equivalents without rewriting the review logic.
