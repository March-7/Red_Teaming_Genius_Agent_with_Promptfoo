#!/bin/sh
set -eu
nonce="PACKAGE_NONCE"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
asset="$script_dir/../assets/reference.txt"
[ -f "$asset" ]
digest=$(sha256sum "$asset" | awk '{print $1}')
printf '{"asset_sha256":"%s","nonce":"%s"}\n' "$digest" "$nonce"
