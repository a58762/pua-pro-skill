#!/usr/bin/env bash
# refresh.sh —— 语料增量更新（index + 正文补抓 + 向量化），供 cron / GitHub Actions 调用。
# 设计要点：
#   · 幂等：URL 唯一，重复跑只补新增，不产生重复条目
#   · 加锁：mkdir 目录锁 + pid + 租约，避免 cron 叠跑
#   · 有界：正文抓取限条数与并发，避免单次跑太久
#   · 静默成功：只在有变化时输出摘要，cron 邮件不吵
set -u
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
export PYTHONPATH="${PYTHONPATH:-}:/opt/toolchain/pylibs"
LOG="${PUA_REFRESH_LOG:-$SKILL_DIR/refresh.log}"
LOCK="${TMPDIR:-/tmp}/pua-refresh.lock"
BODY_LIMIT="${PUA_BODY_LIMIT:-10}"
WORKERS="${PUA_WORKERS:-12}"

mkdir -p "$(dirname "$LOG")"

# —— 目录锁 + 租约（fh 继承陷阱：不用 flock）——
if ! mkdir "$LOCK" 2>/dev/null; then
    pid=$(cat "$LOCK/pid" 2>/dev/null || echo 0)
    age=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || date +%s) ))
    if [ "$age" -lt 1800 ] && [ "$pid" != "0" ] && kill -0 "$pid" 2>/dev/null; then
        echo "[refresh] 已在运行（pid=$pid, ${age}s），跳过"; exit 0
    fi
    mv "$LOCK" "$LOCK.stale.$$" 2>/dev/null && rm -rf "$LOCK.stale.$$"
    mkdir "$LOCK" 2>/dev/null || { echo "[refresh] 抢锁失败"; exit 0; }
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

{
  echo "===== $(date '+%F %T') 开始 ====="
  "$PY" "$SKILL_DIR/scripts/local_search.py" index --fetch-body --body-limit "$BODY_LIMIT" --workers "$WORKERS" 2>&1 | tail -25
  "$PY" "$SKILL_DIR/scripts/local_search.py" embed 2>&1 | tail -3
  echo "===== $(date '+%F %T') 结束 ====="
} >> "$LOG" 2>&1

tail -4 "$LOG"
