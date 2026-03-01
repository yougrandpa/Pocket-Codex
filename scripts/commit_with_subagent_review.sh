#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_BIN="${CODEX_REVIEW_CLI_PATH:-codex}"
MAX_REVIEW_ROUNDS="${MAX_REVIEW_ROUNDS:-5}"
RUN_VERIFY="${RUN_VERIFY_BEFORE_COMMIT:-1}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/commit_with_subagent_review.sh "<commit message>"

Behavior:
  1) Spawn a "review sub-agent" (codex exec, read-only) to review current changes.
  2) If review fails, spawn a "fix sub-agent" to apply fixes.
  3) Repeat review -> fix recursively until review passes.
  4) Run ./scripts/verify_local_env.sh (unless RUN_VERIFY_BEFORE_COMMIT=0).
  5) git add -A && git commit -m "<commit message>".

Env:
  CODEX_REVIEW_CLI_PATH   Codex executable path (default: codex)
  MAX_REVIEW_ROUNDS       Max recursive rounds (default: 5)
  RUN_VERIFY_BEFORE_COMMIT 1 or 0 (default: 1)
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

COMMIT_MESSAGE="$1"

if ! command -v "$CODEX_BIN" >/dev/null 2>&1; then
  echo "[commit-review] codex executable not found: $CODEX_BIN"
  exit 1
fi

cd "$ROOT_DIR"

if [[ ! -d .git ]]; then
  echo "[commit-review] must run inside git repository"
  exit 1
fi

if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
  echo "[commit-review] no local changes to commit"
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
REVIEW_OUTPUT="$TMP_DIR/review.txt"

echo "[commit-review] start recursive sub-agent review"
for ((round = 1; round <= MAX_REVIEW_ROUNDS; round++)); do
  echo "[commit-review] review round $round/$MAX_REVIEW_ROUNDS"
  REVIEW_PROMPT_FILE="$TMP_DIR/review-prompt-$round.txt"
  cat >"$REVIEW_PROMPT_FILE" <<'EOF'
你是代码审查子代理。请仅审查当前 git 工作区改动（包含 staged + unstaged + untracked）。
要求：
1) 不要修改任何文件。
2) 仅输出高价值问题（正确性、稳定性、回归风险、安全、明显性能问题）。
3) 必须按以下固定格式输出：

STATUS:PASS
或
STATUS:FAIL
FINDINGS:
1) <问题标题> | <严重级别:P0/P1/P2> | <文件路径:行号> | <最小修复建议>
2) ...

如果没有问题，输出 STATUS:PASS 且不要输出 FINDINGS 列表。
EOF

  "$CODEX_BIN" exec \
    --skip-git-repo-check \
    -C "$ROOT_DIR" \
    --sandbox read-only \
    --ask-for-approval never \
    --output-last-message "$REVIEW_OUTPUT" \
    - <"$REVIEW_PROMPT_FILE" >/dev/null

  if grep -q "^STATUS:PASS" "$REVIEW_OUTPUT"; then
    echo "[commit-review] review passed"
    break
  fi

  if ! grep -q "^STATUS:FAIL" "$REVIEW_OUTPUT"; then
    echo "[commit-review] reviewer output invalid:"
    cat "$REVIEW_OUTPUT"
    exit 1
  fi

  if [[ "$round" -eq "$MAX_REVIEW_ROUNDS" ]]; then
    echo "[commit-review] reached MAX_REVIEW_ROUNDS=$MAX_REVIEW_ROUNDS but review still failing"
    cat "$REVIEW_OUTPUT"
    exit 1
  fi

  echo "[commit-review] issues found, spawn fix sub-agent"
  FIX_PROMPT_FILE="$TMP_DIR/fix-prompt-$round.txt"
  cat >"$FIX_PROMPT_FILE" <<EOF
你是修复子代理。请根据以下审查意见直接修改代码并修复问题，最小改动优先。
修复后请自行运行必要校验（至少构建/测试中与改动相关的部分）。
不要修改仓库外文件。

审查意见如下：
$(cat "$REVIEW_OUTPUT")
EOF

  "$CODEX_BIN" exec \
    --skip-git-repo-check \
    -C "$ROOT_DIR" \
    --full-auto \
    --ask-for-approval never \
    --output-last-message "$TMP_DIR/fix-result-$round.txt" \
    - <"$FIX_PROMPT_FILE" >/dev/null
done

if [[ "$RUN_VERIFY" == "1" ]]; then
  echo "[commit-review] running verify_local_env"
  ./scripts/verify_local_env.sh
fi

echo "[commit-review] staging files"
git add -A

echo "[commit-review] creating commit"
git commit -m "$COMMIT_MESSAGE"
echo "[commit-review] done"
