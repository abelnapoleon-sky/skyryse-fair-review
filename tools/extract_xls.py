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
