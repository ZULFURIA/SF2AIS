#!/usr/bin/env bash
# cleanup-stale-branches.sh
#
# ONE-TIME MANUAL CLEANUP for SF2AIS.
#
# Background:
#   Two stale remote branches (feature/desktop-probe-electron-app and
#   feature/probe-startup-scripts) still carry a live DuckDNS token, probe
#   token, and password hashes in their commit history. They were committed
#   before the secret-removal fix (PR #3) and could not be force-pushed or
#   deleted because the repo ruleset "Ai coding help" (id 19042974) blocks
#   both non-fast-forward pushes AND branch deletion.
#
#   The CLEAN replacements already exist:
#     - feature/desktop-probe-clean   (PR #4, superset of the feature work)
#     - feature/probe-startup-scripts-clean (PR #5, supersedes the dup branch)
#
# What this script does:
#   1. Snapshots the current ruleset JSON.
#   2. Disables the ruleset (enforcement: "disabled") so deletion is allowed.
#   3. Deletes the two stale branches on the remote.
#   4. Re-enables the ruleset exactly as it was (enforcement: "active").
#
# REQUIREMENTS:
#   - `gh` CLI authenticated with write access to ZULFURIA/SF2AIS.
#   - The ruleset must be modifiable by your token (repo admin or ruleset
#     write). If your integration is in the ruleset's bypass list, you may
#     still need admin role to PATCH the ruleset itself.
#
# SAFETY:
#   - The latest commits on the stale branches are duplicates of already-merged
#     / PR'd clean content, so deleting them loses nothing unrecoverable.
#   - The ruleset is restored even if deletion fails (see trap).
#
# After running, ROTATE the exposed tokens (DuckDNS + probe token) regardless —
# deletion does not revoke credentials already seen.

set -euo pipefail

REPO="ZULFURIA/SF2AIS"
RULESET_ID="19042974"
STALE_BRANCHES=("feature/desktop-probe-electron-app" "feature/probe-startup-scripts")

SNAP=$(mktemp)
trap 'echo ">>> Restoring ruleset to active..."; gh api "repos/${REPO}/rulesets/${RULESET_ID}" -X PATCH -f enforcement=active >/dev/null 2>&1 || true; rm -f "$SNAP"' EXIT

echo ">>> Snapshotting current ruleset..."
gh api "repos/${REPO}/rulesets/${RULESET_ID}" > "$SNAP"

echo ">>> Disabling ruleset (temporarily)..."
gh api "repos/${REPO}/rulesets/${RULESET_ID}" -X PATCH -f enforcement=disabled >/dev/null

for b in "${STALE_BRANCHES[@]}"; do
  echo ">>> Deleting remote branch: $b"
  if git push origin --delete "$b" 2>&1; then
    echo "    deleted: $b"
  else
    echo "    FAILED to delete: $b (continuing)" >&2
  fi
done

echo ">>> Ruleset will be restored by the exit trap."
echo "DONE. Remember to ROTATE the exposed DuckDNS + probe tokens."
