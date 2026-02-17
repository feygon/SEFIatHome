#!/usr/bin/env bash
# =============================================================================
# orchestrator.sh — SEFI@Home multi-agent development pipeline
#
# Runs 3 Claude Code agents per task:
#   Agent 1 (Programmer)  — implements the task
#   Agent 2 (Tester)      — reviews, fixes, writes tests
#   Agent 3 (Committer)   — commits, updates docs, pushes
#
# Usage:
#   ./orchestrator.sh              # process next pending task
#   ./orchestrator.sh US-001       # process a specific task
#   ./orchestrator.sh --loop       # process all pending tasks in sequence
#   ./orchestrator.sh --dry-run    # find next task, print it, do nothing
#
# Token limits: each agent retries up to MAX_RETRIES times, waiting
# RETRY_WAIT seconds between attempts, so the script can recover from
# rate limits and temporary overloads without manual intervention.
# =============================================================================

set -euo pipefail

# ── Windows/Git Bash: tell claude CLI where bash.exe lives ───────────────────
# Required when claude is invoked as a subprocess from within Git Bash.
# Detected automatically; override by setting this env var before running.
if [ -z "${CLAUDE_CODE_GIT_BASH_PATH:-}" ]; then
    _detected_bash="$(cygpath -w /usr/bin/bash 2>/dev/null || echo "")"
    if [ -n "$_detected_bash" ]; then
        export CLAUDE_CODE_GIT_BASH_PATH="$_detected_bash"
    fi
fi

# ── Paths (resolved relative to this script's location) ─────────────────────
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TODO_DIR="$REPO_DIR/todo"
LOG_FILE="$REPO_DIR/orchestrator.log"

# ── Model identifiers ────────────────────────────────────────────────────────
SONNET="claude-sonnet-4-5-20250929"
OPUS="claude-opus-4-5-20251101"
DEFAULT_MODEL="$SONNET"

# ── Retry config ─────────────────────────────────────────────────────────────
MAX_RETRIES=5
RETRY_WAIT=120   # seconds to wait after a probable token/rate-limit hit

# ── Logging ──────────────────────────────────────────────────────────────────
log() {
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] $*" | tee -a "$LOG_FILE"
}

# ── Task discovery ────────────────────────────────────────────────────────────

# Returns 0 (true) if all dependencies of a task file are done, 1 otherwise.
deps_satisfied() {
    local file="$1"
    local dep_line dep
    dep_line=$(grep "\*\*Depends On:\*\*" "$file" 2>/dev/null \
               | sed 's/.*\*\*Depends On:\*\*[[:space:]]*//' \
               | tr -d '\r')

    # No dependency line or explicitly None/—
    [[ -z "$dep_line" || "$dep_line" == "None" || "$dep_line" == "—" ]] && return 0

    # Split on commas, check each dep is done
    IFS=',' read -ra deps <<< "$dep_line"
    for dep in "${deps[@]}"; do
        dep="$(echo "$dep" | tr -d ' \t')"
        [[ -z "$dep" ]] && continue
        local dep_file="$TODO_DIR/${dep}.md"
        if [ ! -f "$dep_file" ]; then
            log "  WARN: dependency file not found: $dep_file (treating as unsatisfied)"
            return 1
        fi
        if ! grep -q "\*\*Status:\*\*[[:space:]]*done" "$dep_file" 2>/dev/null; then
            return 1   # dep exists but is not done
        fi
    done
    return 0
}

find_next_task() {
    # Returns path of first US-*.md that is pending AND has all deps done.
    # Logs skipped tasks so the user can see why they were bypassed.
    local skipped=0
    for f in "$TODO_DIR"/US-*.md; do
        [ -f "$f" ] || continue
        if ! grep -q "\*\*Status:\*\*[[:space:]]*pending" "$f" 2>/dev/null; then
            continue   # not pending — already done/in_progress/failed
        fi
        if deps_satisfied "$f"; then
            echo "$f"
            return 0
        else
            log "  Skipping $(basename "$f" .md) — dependencies not yet done"
            skipped=$((skipped + 1))
        fi
    done
    [ "$skipped" -gt 0 ] && log "  $skipped task(s) pending but blocked on dependencies."
    echo ""
}

# ── Metadata helpers ──────────────────────────────────────────────────────────
get_task_model() {
    # Reads the Model: line from the task file; defaults to sonnet
    local file="$1"
    local spec
    spec=$(grep -m1 "\*\*Model:\*\*" "$file" 2>/dev/null \
           | sed 's/.*\*\*Model:\*\*[[:space:]]*//' \
           | tr -d '[:space:]') || spec=""
    case "${spec,,}" in
        opus)  echo "$OPUS" ;;
        *)     echo "$SONNET" ;;
    esac
}

get_task_id() {
    basename "$1" .md
}

# ── Status management ─────────────────────────────────────────────────────────
set_status() {
    local file="$1" new_status="$2"
    # Portable sed: works on GNU (Linux/WSL) and BSD (macOS/Git Bash on macOS)
    if sed --version 2>/dev/null | grep -q GNU; then
        sed -i "s|\*\*Status:\*\*[[:space:]]*[a-z_]*|\*\*Status:\*\* ${new_status}|" "$file"
    else
        sed -i '' "s|\*\*Status:\*\*[[:space:]]*[a-z_]*|\*\*Status:\*\* ${new_status}|" "$file"
    fi
}

# ── Claude runner with retry ──────────────────────────────────────────────────
run_claude() {
    # Args: <model> <prompt-file> [<output-file>]
    local model="$1"
    local prompt_file="$2"
    local out_file="${3:-}"
    local attempt=0

    while [ "$attempt" -lt "$MAX_RETRIES" ]; do
        attempt=$((attempt + 1))
        log "    claude ($model) attempt $attempt/$MAX_RETRIES ..."

        local output exit_code
        set +e
        output=$(claude \
            --model "$model" \
            --dangerously-skip-permissions \
            --print "$(cat "$prompt_file")" 2>&1)
        exit_code=$?
        set -e

        if [ "$exit_code" -eq 0 ]; then
            [ -n "$out_file" ] && echo "$output" > "$out_file"
            log "    Agent succeeded."
            return 0
        fi

        # Detect token/rate/context limit signals in output or exit code
        if echo "$output" | grep -qiE \
            "context.*(limit|window|length|too long)|too (many|long)|token.*limit|rate.?limit|overloaded|529|503"; then
            log "    Rate/token limit detected. Waiting ${RETRY_WAIT}s before retry..."
            sleep "$RETRY_WAIT"
        else
            # Non-retryable failure — log last 10 lines and abort
            log "    Non-retryable failure (exit $exit_code). Last output:"
            echo "$output" | tail -10 | while IFS= read -r line; do
                log "    | $line"
            done
            return 1
        fi
    done

    log "    All $MAX_RETRIES retries exhausted."
    return 1
}

# ── Agent prompts ─────────────────────────────────────────────────────────────
write_programmer_prompt() {
    local task_file="$1" task_id="$2"
    cat > "$3" <<PROMPT
You are the Programmer agent for the SEFI@Home project.

Working directory: $REPO_DIR
Your task: $task_id
Task file: $task_file

## Instructions

1. Read $task_file for requirements, acceptance criteria, and files to create.
2. Read $REPO_DIR/ROADMAP.md and $REPO_DIR/plans/requirements.md for architecture context.
3. Read $REPO_DIR/AGENTS.md for code conventions.
4. Implement the task completely. All source files go under $REPO_DIR/src/.

## Code Conventions (mandatory)

- Python 3.10+ with type annotations on every function and method
- Pydantic v2 BaseModel for all data structures crossing module boundaries
- Raw SQL with parameterized queries (? placeholders). No ORM.
- Docstrings on every public class, function, and method
- No live HTTP calls. Any network access must go through an injectable callable
  so tests can swap in a mock (e.g. check_url_exists: Callable[[str], bool])

## Documentation (mandatory — blocking)

For every module you create or significantly modify, write a corresponding
API doc in $REPO_DIR/docs/api/<module_name>.md. Follow this structure:

\`\`\`markdown
# <Module Name>

**Module:** \`sefi.<subpackage>.<module>\`
**Purpose:** One sentence.

## Classes

### ClassName
Brief description.
| Method | Args | Returns | Description |
|--------|------|---------|-------------|
| method_name | arg: type | type | what it does |

## Functions

### function_name(args) -> return_type
Brief description. Note any exceptions raised.

## Usage Example
\`\`\`python
# minimal working example
\`\`\`
\`\`\`

Create $REPO_DIR/docs/api/ if it does not exist.
Do NOT document private helpers (names starting with _).

## Constraints

- Do NOT write tests (that is the Tester's job)
- Do NOT commit (that is the Committer's job)
- Do NOT download corpus databases (zero-corpus design)

## When Done

Update the Status field in $task_file from "pending" to "in_review".
Then print: PROGRAMMER DONE: $task_id
PROMPT
}

write_tester_prompt() {
    local task_file="$1" task_id="$2"
    cat > "$3" <<PROMPT
You are the Tester agent for the SEFI@Home project.

Working directory: $REPO_DIR
Task just implemented: $task_id
Task file: $task_file

## Instructions

1. Read $task_file to understand what was implemented and its acceptance criteria.
2. Read every source file created/modified by the Programmer under $REPO_DIR/src/.
3. Review the code for:
   - Type annotation coverage
   - Docstring presence on public APIs
   - SQL parameterization (no string interpolation)
   - Correct Pydantic v2 usage
4. Fix any violations you find directly in the source files.
5. Write pytest tests in $REPO_DIR/tests/ that cover:
   - Every acceptance criterion listed in $task_file (one test per criterion minimum)
   - Key error paths and edge cases
   - Use unittest.mock or pytest-mock to mock ALL HTTP calls
     (no live requests to justice.gov or any external URL)
   - Use in-memory SQLite (:memory:) for database tests
6. Run: python -m pytest $REPO_DIR/tests/ -x -q
7. Fix failures until the full suite passes.

## When Done

Update the Status field in $task_file from "in_review" to "tested".
Then print: TESTER DONE: $task_id
PROMPT
}

write_committer_prompt() {
    local task_file="$1" task_id="$2"
    cat > "$3" <<PROMPT
You are the Committer agent for the SEFI@Home project.

Working directory: $REPO_DIR
Task to commit: $task_id
Task file: $task_file

## Instructions

1. Run: python -m pytest $REPO_DIR/tests/ -q
   If ANY test fails, STOP. Print "COMMIT BLOCKED: tests failing." and exit.

1b. Verify $REPO_DIR/docs/api/ contains at least one .md file created or
   modified for this task. If docs/api/ is missing or empty for the modules
   this task touched, STOP. Print "COMMIT BLOCKED: docs/api/ not written."
   and exit. Do NOT commit undocumented work.

2. Stage relevant files only:
   git -C $REPO_DIR add src/ tests/ docs/ todo/ pyproject.toml

3. Write a commit message:
   - Subject line: "$task_id: <one-line summary of what was implemented>"
   - Body: bullet list of files added and what each does
   - Footer: "Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

4. Commit:
   git -C $REPO_DIR commit -m "<your message>"

5. Update $task_file: change Status from "tested" to "done".

6. Update $REPO_DIR/todo/SUMMARY.md: mark this task as done in the table.

7. Update $REPO_DIR/ROADMAP.md: find the section for this component and add
   a "✅ Implemented (US-NNN)" note.

8. Stage and commit those documentation updates with message:
   "docs: mark $task_id complete in roadmap and todo"

9. Push: git -C $REPO_DIR push

10. Print: COMMITTER DONE: $task_id
PROMPT
}

# ── Pipeline ──────────────────────────────────────────────────────────────────
run_task_pipeline() {
    local task_file="$1"
    local task_id
    task_id="$(get_task_id "$task_file")"
    local model
    model="$(get_task_model "$task_file")"

    log "════════════════════════════════════════════"
    log "  Task : $task_id"
    log "  Model: $model"
    log "  File : $task_file"
    log "════════════════════════════════════════════"

    # Claim the task immediately so parallel runs don't double-claim it
    set_status "$task_file" "in_progress"
    log "  Claimed $task_id (status → in_progress)"

    # Write prompts to temp files — avoids shell quoting issues with heredocs
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '$tmp_dir'" EXIT

    local p_prog="$tmp_dir/programmer.txt"
    local p_test="$tmp_dir/tester.txt"
    local p_comm="$tmp_dir/committer.txt"

    write_programmer_prompt "$task_file" "$task_id" "$p_prog"
    write_tester_prompt     "$task_file" "$task_id" "$p_test"
    write_committer_prompt  "$task_file" "$task_id" "$p_comm"

    # ── Agent 1: Programmer ──────────────────────────────────────────────────
    log "  ── Agent 1: Programmer (model: $model) ──"
    if ! run_claude "$model" "$p_prog"; then
        log "  FATAL: Programmer failed for $task_id"
        set_status "$task_file" "failed_programmer"
        exit 1
    fi

    # ── Agent 2: Tester (same model as Programmer — workflow rule) ───────────
    log "  ── Agent 2: Tester (model: $model) ──"
    if ! run_claude "$model" "$p_test"; then
        log "  FATAL: Tester failed for $task_id"
        set_status "$task_file" "failed_tester"
        exit 1
    fi

    # ── Agent 3: Committer (always Sonnet — just git ops) ───────────────────
    log "  ── Agent 3: Committer (model: $SONNET) ──"
    if ! run_claude "$SONNET" "$p_comm"; then
        log "  FATAL: Committer failed for $task_id"
        set_status "$task_file" "failed_committer"
        exit 1
    fi

    log "  ════ $task_id COMPLETE ════"
}

# ── Entry point ───────────────────────────────────────────────────────────────
main() {
    log "orchestrator.sh started  (repo: $REPO_DIR)"

    local arg="${1:-}"

    case "$arg" in

        --dry-run)
            # Find next task, print it, do nothing else
            local task
            task="$(find_next_task)"
            if [ -z "$task" ]; then
                log "No pending tasks."
            else
                log "Next pending task: $(get_task_id "$task")  ($(get_task_model "$task"))"
                log "Dry run — no agents launched."
            fi
            ;;

        --loop)
            # Process all pending tasks one at a time
            while true; do
                local task
                task="$(find_next_task)"
                if [ -z "$task" ]; then
                    log "No more pending tasks. All done."
                    break
                fi
                run_task_pipeline "$task"
            done
            ;;

        "")
            # Process the next pending task only
            local task
            task="$(find_next_task)"
            if [ -z "$task" ]; then
                log "No pending tasks found."
                exit 0
            fi
            run_task_pipeline "$task"
            ;;

        US-*)
            # Process a specific task by ID
            local task_file="$TODO_DIR/${arg}.md"
            if [ ! -f "$task_file" ]; then
                log "ERROR: Task file not found: $task_file"
                exit 1
            fi
            run_task_pipeline "$task_file"
            ;;

        *)
            echo "Usage: $0 [US-NNN | --loop | --dry-run]"
            exit 1
            ;;
    esac
}

main "$@"
