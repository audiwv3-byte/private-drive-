"""Tracked-tree credential checks. Never emit secret values."""
import re
import subprocess
from pathlib import Path

patterns = {
    "private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "github-token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{60,255})\b",
    "stripe-live": rb"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b",
    "aws-key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "telegram-token": rb"\b[0-9]{8,12}:[A-Za-z0-9_-]{35}\b",
}
def main():
    paths=subprocess.check_output(["git","ls-files","-z"]).decode().split("\0")
    hits=[]
    scanned=0
    for name in filter(None,paths):
        p=Path(name)
        if p.name.startswith(".env") and p.name not in {".env.example",".env.sample",".env.template"} or p.suffix.lower() in {".p12",".pfx",".jks",".keystore",".mobileprovision"}:
            hits.append((name,"credential-file"))
        if not p.is_file() or p.is_symlink(): continue
        raw=p.read_bytes()
        if b"\0" in raw[:8192]: continue
        scanned+=1
        if name=="ops/qa/qa35_secret_scan.py": continue
        for kind,pattern in patterns.items():
            for m in re.finditer(pattern,raw):
                hits.append((name,kind,raw.count(b"\n",0,m.start())+1))
    print(f"Scanned {scanned} tracked text files; {len(hits)} findings")
    for hit in hits: print(*hit)
    if hits: raise SystemExit(1)
if __name__=="__main__": main()
