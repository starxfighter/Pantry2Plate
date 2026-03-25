#!/usr/bin/env bash
# =============================================================================
# init_memory.sh — Pantry-to-Plate project memory bootstrap checker
#
# Verifies that all expected memory reference files are present and non-empty.
# Run from the repo root:
#   bash .claude/skills/project-memory/scripts/init_memory.sh
# =============================================================================

set -euo pipefail

MEMORY_DIR=".claude/skills/project-memory"
REFS_DIR="${MEMORY_DIR}/references"

GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

pass() { echo -e "  ${GREEN}✔${RESET}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
fail() { echo -e "  ${RED}✘${RESET}  $1"; }

errors=0

echo ""
echo "Pantry-to-Plate — Project Memory Bootstrap Check"
echo "================================================="
echo ""

# ── Required files ────────────────────────────────────────────────────────────
REQUIRED_FILES=(
  "${MEMORY_DIR}/SKILL.md"
  "${REFS_DIR}/progress.md"
  "${REFS_DIR}/context.md"
  "${REFS_DIR}/todo.md"
  "${REFS_DIR}/decisions.md"
  "${REFS_DIR}/bugs.md"
  "${MEMORY_DIR}/scripts/init_memory.sh"
)

echo "Checking memory files..."
for f in "${REQUIRED_FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    fail "Missing: $f"
    (( errors++ )) || true
  elif [[ ! -s "$f" ]]; then
    warn "Empty:   $f"
  else
    pass "$f"
  fi
done

# ── RESUME HERE marker ────────────────────────────────────────────────────────
echo ""
echo "Checking RESUME HERE marker..."
PROGRESS_FILE="${REFS_DIR}/progress.md"
if [[ -f "$PROGRESS_FILE" ]]; then
  if grep -q "RESUME HERE" "$PROGRESS_FILE"; then
    pass "RESUME HERE marker found in progress.md"
    echo ""
    echo "  ── Current resume point ──────────────────────────────────────────"
    # Print the lines immediately following the marker
    awk '/RESUME HERE/{found=1; next} found && /^---/{exit} found{print "  " $0}' "$PROGRESS_FILE"
    echo "  ──────────────────────────────────────────────────────────────────"
  else
    fail "No RESUME HERE marker in progress.md"
    (( errors++ )) || true
  fi
fi

# ── Open bugs ─────────────────────────────────────────────────────────────────
echo ""
echo "Checking open bugs..."
BUGS_FILE="${REFS_DIR}/bugs.md"
if [[ -f "$BUGS_FILE" ]]; then
  open_count=$(grep -cP "^\- \*\*Status:\*\* (Open|In Progress)$" "$BUGS_FILE" 2>/dev/null || true)
  if [[ "$open_count" -gt 0 ]]; then
    warn "${open_count} open bug(s) — check bugs.md before starting work"
  else
    pass "No open bugs"
  fi
fi

# ── Incomplete todo phases ────────────────────────────────────────────────────
echo ""
echo "Checking todo phases..."
TODO_FILE="${REFS_DIR}/todo.md"
if [[ -f "$TODO_FILE" ]]; then
  incomplete=$(grep -c "^\- \[ \]" "$TODO_FILE" 2>/dev/null || true)
  complete=$(grep -c "^\- \[x\]" "$TODO_FILE" 2>/dev/null || true)
  pass "Tasks complete: ${complete}  |  Tasks remaining: ${incomplete}"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "================================================="
if [[ "$errors" -eq 0 ]]; then
  echo -e "${GREEN}All checks passed. Memory system is healthy.${RESET}"
else
  echo -e "${RED}${errors} error(s) found. Run from the repo root and ensure all${RESET}"
  echo -e "${RED}memory files have been created before starting a session.${RESET}"
  exit 1
fi
echo ""
