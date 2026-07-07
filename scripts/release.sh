#!/usr/bin/env bash
#
# release.sh — cut an engine release and retire the previous stable version for
# good, in one atomic step. This exists because the recurring "old engine keeps
# coming back" problem is caused by forgetting to (a) bump the channel manifest
# and (b) purge jsDelivr's moving refs. This script always does both.
#
# Usage:
#   scripts/release.sh 2.6.0             # FULL release: stable -> 2.6.0 (everyone)
#   scripts/release.sh 2.6.0 --canary 10 # CANARY: 10% of loads get 2.6.0, stable unchanged
#   scripts/release.sh 2.6.0 --yes       # skip the confirmation prompt
#
# What a FULL release does:
#   1. Bumps VERSION, engine ENGINE_VERSION, loader FALLBACK to the new version.
#   2. Points channel.json stable + canary at the new version (canaryPct=0).
#   3. Rewrites the @vX.Y.Z jsDelivr refs in index.html + demo/publisher-test.html
#      (so the version-check CI stays green).
#   4. Commits, tags vX.Y.Z, pushes the branch + tag.
#   5. Purges the jsDelivr MOVING refs (@2/loader.js, @main/channel.json) so the
#      new stable is served immediately — this is the step that's easy to forget.
#
set -euo pipefail

REPO="shashwatsilverpush/bidding-player"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ── args ─────────────────────────────────────────────────────────────────────
VERSION="${1:-}"
CANARY_PCT=""
ASSUME_YES=0
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --canary) CANARY_PCT="${2:-}"; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if ! echo "${VERSION}" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "error: version must look like X.Y.Z (got '${VERSION}')" >&2
  echo "usage: scripts/release.sh X.Y.Z [--canary PCT] [--yes]" >&2
  exit 2
fi
MODE="full"; [ -n "${CANARY_PCT}" ] && MODE="canary"

# ── safety checks ────────────────────────────────────────────────────────────
if [ -n "$(git status --porcelain)" ]; then
  echo "error: working tree not clean — commit or stash first." >&2
  git status --short >&2
  exit 1
fi
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "${BRANCH}" != "main" ]; then
  echo "warning: you are on '${BRANCH}', not 'main'. Releases normally cut from main." >&2
fi
if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
  echo "error: tag v${VERSION} already exists." >&2
  exit 1
fi

echo "── Release plan ───────────────────────────────────────────"
echo "  version : v${VERSION}"
echo "  mode    : ${MODE}$( [ "${MODE}" = canary ] && echo " (${CANARY_PCT}% rollout, stable unchanged)" )"
echo "  branch  : ${BRANCH}"
echo "───────────────────────────────────────────────────────────"

# ── edit files ───────────────────────────────────────────────────────────────
py_channel() {  # $1=stable-or-keep  $2=canary  $3=pct
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
stable, canary, pct = sys.argv[1], sys.argv[2], sys.argv[3]
p = "engine/channel.json"
m = json.load(open(p))
if stable != "KEEP":
    m["stable"] = stable
m["canary"] = canary
m["canaryPct"] = int(pct)
json.dump(m, open(p, "w"), indent=2)
open(p, "a").write("\n")
PY
}

if [ "${MODE}" = "full" ]; then
  echo "${VERSION}" > VERSION
  # engine + loader version constants
  sed -i.bak -E "s/(var ENGINE_VERSION = \")[0-9.]+(\";)/\1${VERSION}\2/" engine/player.js && rm -f engine/player.js.bak
  sed -i.bak -E "s/(var FALLBACK = \")[0-9.]+(\";)/\1${VERSION}\2/" engine/loader.js && rm -f engine/loader.js.bak
  # channel manifest: full rollout
  py_channel "${VERSION}" "${VERSION}" 0
  # jsDelivr @vX.Y.Z refs in the dashboard + demo (version-check CI)
  for f in index.html demo/publisher-test.html; do
    sed -i.bak -E "s#(bidding-player@)v[0-9.]+/#\1v${VERSION}/#g" "$f" && rm -f "$f.bak"
  done
else
  # canary: keep stable, point canary at the new version at PCT%
  py_channel "KEEP" "${VERSION}" "${CANARY_PCT}"
fi

echo "── Pending changes ────────────────────────────────────────"
git --no-pager diff --stat
echo "───────────────────────────────────────────────────────────"

if [ "${ASSUME_YES}" -ne 1 ]; then
  printf "Commit, tag v%s, push, and purge jsDelivr? [y/N] " "${VERSION}"
  read -r ans
  case "${ans}" in y|Y|yes|YES) ;; *) echo "aborted (no changes pushed; files edited locally)."; exit 1 ;; esac
fi

# ── commit + tag + push ──────────────────────────────────────────────────────
git add -A
if [ "${MODE}" = "full" ]; then
  git commit -m "Release v${VERSION}"
else
  git commit -m "Canary v${VERSION} at ${CANARY_PCT}%"
fi
git tag "v${VERSION}"
git push origin "${BRANCH}"
git push origin "v${VERSION}"

# ── purge jsDelivr moving refs (THE step that's easy to forget) ──────────────
echo "── Purging jsDelivr ───────────────────────────────────────"
PURGE=(
  "@main/engine/channel.json"   # the loader reads this to resolve the version
  "@2/engine/loader.js"         # the auto-update entry point
)
# On a full release also warm/refresh the pinned engine + prebid paths.
if [ "${MODE}" = "full" ]; then
  PURGE+=("@v${VERSION}/engine/player.js" "@v${VERSION}/engine/loader.js" "@v${VERSION}/prebid/prebid.js")
fi
for ref in "${PURGE[@]}"; do
  url="https://purge.jsdelivr.net/gh/${REPO}${ref}"
  code=$(curl -s -o /dev/null -w "%{http_code}" "${url}" || echo "000")
  echo "  purge ${ref} -> HTTP ${code}"
done

echo "───────────────────────────────────────────────────────────"
echo "Released v${VERSION} (${MODE}). Give jsDelivr ~1 min, then hard-reload a"
echo "publisher page and confirm the engine reports version ${VERSION}."
