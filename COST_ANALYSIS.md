# FAIR Review Tool — Cost Analysis (AI Document Reading)

**Prepared for:** Skyryse Leadership / Supplier Quality
**Prepared by:** Abel Napoleon
**Date:** June 12, 2026
**Scope:** The per-use AI cost of having the tool read a FAIR package and produce a review. Infrastructure/hosting cost is separate (see System Requirements).

---

## Executive summary

- **Reviewing one FAIR package costs about $0.72** in AI usage (measured on a real 7-document package).
- At the pilot volume of **40 FAIR packages, the total AI cost is roughly $29** (review only) to **$43** (if every package also gets the optional pre-check).
- If the team processes **40 FAIRs per month, that annualizes to roughly $350–$520/year.**
- Cost is **pay-per-use** — no per-seat licenses, no minimums. You pay only for packages actually reviewed.
- For context, each package produces a thorough traceability + completeness draft in ~2–3 minutes that would otherwise take an engineer a significant share of an hour to assemble by hand.

These are small, predictable operating costs relative to the engineering time they offset.

---

## How the tool is priced

The tool uses Anthropic's Claude Opus 4.8 model on a **per-token** basis (a token ≈ ¾ of a word; a scanned page image counts as a few thousand tokens). Published rates:

| Item | Rate |
|---|---|
| Input (documents read in) | $5.00 per 1,000,000 tokens |
| Output (the written review) | $25.00 per 1,000,000 tokens |
| Cached input (the quality-clause baseline, reused) | $0.50 per 1,000,000 tokens |

There are no licensing, seat, or subscription fees — cost is purely usage.

## Measured example — part 1101021 (a real 7-document package)

This is the actual usage from a live review of the 1101021 FAIR package (FAIR Excel workbook, drawing, CoC/packing slip, 34-page material & process certs, two NADCAP certs, inspection report — several of them scanned):

| Component | Tokens | Cost |
|---|---|---|
| Documents read in (input) | 70,331 | $0.352 |
| Quality-clause baseline (cached) | 8,552 | $0.053 |
| Review written out (output) | 12,479 | $0.312 |
| **Total — one full review** | | **≈ $0.72** |

The bulk of the cost is **reading the scanned document images**; the written review itself is a small fraction.

## Per-package cost

| Action | What it does | Cost (typical) |
|---|---|---|
| **Full review** | Reads the whole package, produces verdict + traceability chain + findings | **~$0.72** |
| **Document pre-check (optional)** | Reads the package to confirm Part #/PO/Supplier are present and auto-fill the part name | **~$0.35** (estimated) |
| **Both, per package** | Pre-check then full review | **~$1.08** |

> The pre-check is optional — the full review already extracts those fields, so teams can skip the separate pre-check to roughly halve per-package cost (see Optimization below).

## Volume projections

**At the stated pilot volume (40 FAIR packages):**

| Scenario | Cost |
|---|---|
| Review only (40 × $0.72) | **~$29** |
| Review + pre-check (40 × $1.08) | **~$43** |

**If 40 FAIR packages are processed every month (annualized):**

| Scenario | Monthly | Annual |
|---|---|---|
| Review only | ~$29 | **~$345** |
| Review + pre-check | ~$43 | **~$518** |

## Cost drivers & sensitivity

The single biggest driver is the **number of scanned pages** in the package — each scanned page is read as an image and costs more than machine-readable text. Package size therefore moves the cost:

| Package size | Example | Est. cost per review |
|---|---|---|
| Small detail FAIR | ~3–5 docs, few scanned pages | ~$0.30–0.45 |
| Typical (like 1101021) | 7 docs, several scanned certs | ~$0.70 |
| Large assembly FAIR | many sub-tier certs, 40+ scanned pages | ~$1.50–3.00 |

Even at the high end, a single package stays in the low single-dollar range.

## Ways to reduce cost (already available or easy)

1. **Skip the separate pre-check** — fold metadata extraction into the single review pass (the review already returns those fields). Eliminates the second document read; ~50% saving per package.
2. **Quality-clause caching** — the Skyryse clause baseline is cached and billed at 1/10th rate on repeat runs (already implemented).
3. **Use a lighter model for the pre-check** — the simple "is it there / what's the part name" extraction does not need the top model; a smaller model would cut the pre-check cost substantially.
4. **Text-native documents are cheaper** — suppliers submitting machine-readable PDFs (vs. scans) lowers input cost; a future supplier guidance point.

## Value framing (illustrative)

The AI cost should be weighed against the engineering time it offsets. *Illustrative only — adjust to Skyryse's actual loaded rates:*

- A manual first-pass FAIR completeness/traceability review can take an engineer on the order of **1–2 hours**.
- At a loaded rate of, say, **$60/hour**, that is **$60–$120 of labor** per package.
- The tool produces the same first-pass draft for **under $1 in ~2–3 minutes**, with the engineer then verifying and making the final call.

The AI cost is a small fraction of one percent of the associated engineering time, and it improves consistency (every package checked against the same clause baseline).

## What this analysis does NOT include

- **Hosting/infrastructure** for the multi-user deployment (compute, database, storage) — a separate, modest operating cost covered in the System Requirements document (order of a few hundred dollars/month on AWS).
- **One-time development** to build the multi-user version.
- These per-package AI costs carry over essentially unchanged whether the AI runs via the direct API or via Amazon Bedrock in GovCloud.
