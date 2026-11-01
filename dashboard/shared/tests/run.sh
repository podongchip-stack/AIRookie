#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CHECK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/goldenlink-sync-check.XXXXXX")
swiftc -parse-as-library -module-cache-path "$CHECK_DIR/cache" "$HERE/../CaseEditSync.swift" "$HERE/CaseEditSyncChecks.swift" -o "$CHECK_DIR/check"
"$CHECK_DIR/check"
