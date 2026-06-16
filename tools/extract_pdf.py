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
