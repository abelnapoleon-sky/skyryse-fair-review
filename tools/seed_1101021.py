"""Seed the app with the 1101021 package via the real upload API (also a smoke test)."""
import urllib.request
import uuid
import json
from pathlib import Path

FILES = [
    r"C:\Users\AbelNapoleon\Downloads\PL_COC_SEP_282_1101021 (1).pdf",
    r"C:\Users\AbelNapoleon\Downloads\1101021_FAIR_Rev-.xls",
    r"C:\Users\AbelNapoleon\Downloads\AH PS 3307.pdf",
    r"C:\Users\AbelNapoleon\Downloads\MATERIAL & PROCESS CERTS (1).pdf",
    r"C:\Users\AbelNapoleon\Downloads\NADCAP CHEMICAL PROCESS BARRY AVE.pdf",
    r"C:\Users\AbelNapoleon\Downloads\NADCAP AEROSPACE QUALITY SYSTEM (AC7004) BARRY AVE.pdf",
    r"C:\Users\AbelNapoleon\Downloads\1101021_INSP_Rev-.pdf",
]

fields = {
    "part_number": "1101021-01",
    "revision": "-",
    "supplier": "AH Machine Inc",
    "po_number": "3307",
    "notes": "Screw, shoulder, #4, black. Make-from MS51576-3 + black oxide AMS 2485. NHA 1101802 Control Stick.",
}

boundary = uuid.uuid4().hex
body = b""
for k, v in fields.items():
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
for fp in FILES:
    p = Path(fp)
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{p.name}\"\r\n"
             f"Content-Type: application/octet-stream\r\n\r\n").encode()
    body += p.read_bytes() + b"\r\n"
body += f"--{boundary}--\r\n".encode()

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/parts",
    data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    print(resp.status, json.loads(resp.read()))
