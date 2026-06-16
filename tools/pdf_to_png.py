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
