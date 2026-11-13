"""Boot test in a subprocess with a FRESH temp data dir."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = r"""
import os, sys
sys.path.insert(0, os.path.join(%r, ".."))
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    b = c.get("/api/build").json()
    assert b["build"] == "Build 2026-11-13 \u00b7 Cardable v0.2", b
    s = c.get("/api/status").json()
    assert s["ok"] is True, s
    idx = c.get("/")
    assert idx.status_code == 200 and "CARDABLE" in idx.text
    p = c.post("/api/players", json={"name": "Boot"})
    assert p.status_code == 200
print("boot ok")
""" % HERE


def main():
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, DATA_DIR=os.path.join(td, "fresh"))
        r = subprocess.run([sys.executable, "-c", CODE], env=env,
                           capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode != 0:
            print(r.stderr)
            raise SystemExit("BOOT TEST FAILED")
    print("BOOT TEST PASSED")


if __name__ == "__main__":
    main()
