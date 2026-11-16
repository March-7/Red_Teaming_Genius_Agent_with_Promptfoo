from __future__ import annotations
import hashlib
import json
from pathlib import Path

nonce = "PACKAGE_NONCE"
script = Path(__file__).resolve()
asset = next((parent / "assets/reference.txt" for parent in script.parents
              if (parent / "assets/reference.txt").is_file()), None)
if asset is None:
    raise SystemExit("package asset missing")
data = asset.read_bytes()
print(json.dumps({"nonce": nonce,
                  "asset_sha256": hashlib.sha256(data).hexdigest()},
                 sort_keys=True, separators=(",", ":")))
