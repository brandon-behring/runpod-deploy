#!/usr/bin/env bash
#
# Backfill GitHub releases for every tag that doesn't already have one.
# Release notes are extracted from the corresponding `## [X.Y.Z]` section
# of CHANGELOG.md.
#
# Idempotent: skips tags that already have a release; safe to re-run.
#
# Usage:
#   scripts/backfill_releases.sh [tag1 tag2 ...]
#
# With no args: backfills every git tag of the form `v*` that exists on
# origin. With args: backfills only the listed tags.
#
# Prereqs: `gh` authenticated, working directory at repo root, CHANGELOG.md
# present.

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f CHANGELOG.md ]; then
  echo "ERROR: CHANGELOG.md not found in $(pwd)" >&2
  exit 1
fi

# Tag list: explicit args, or all `v*` tags on origin sorted by version.
if [ $# -gt 0 ]; then
  tags=("$@")
else
  mapfile -t tags < <(git tag --list 'v*' --sort=v:refname)
fi

extract_notes() {
  # $1 = version like "0.7.4". Pulls the `## [0.7.4]` section out of
  # CHANGELOG.md, stopping at the next `## [` line (next version header).
  local version="$1"
  awk -v ver="$version" '
    BEGIN { in_section = 0 }
    /^## \[/ {
      if (in_section) { exit }
      if ($0 ~ "^## \\[" ver "\\]") { in_section = 1; print; next }
    }
    in_section { print }
  ' CHANGELOG.md
}

created=0
skipped=0
missing=0

for tag in "${tags[@]}"; do
  version="${tag#v}"

  if gh release view "$tag" >/dev/null 2>&1; then
    echo "==> $tag: release already exists; skipping"
    skipped=$((skipped + 1))
    continue
  fi

  notes=$(extract_notes "$version")
  if [ -z "$notes" ]; then
    echo "==> $tag: no CHANGELOG section found for $version; skipping" >&2
    missing=$((missing + 1))
    continue
  fi

  echo "==> $tag: creating release"
  gh release create "$tag" --title "$tag" --notes "$notes"
  created=$((created + 1))
done

echo
echo "Backfill summary:"
echo "  created: $created"
echo "  skipped (already exist): $skipped"
echo "  missing CHANGELOG section: $missing"
echo "  total tags considered: ${#tags[@]}"
