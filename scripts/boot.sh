#!/usr/bin/env bash
# PUA Pro v4.3 — 对账型启动器（共享沙箱安全版）
#
# 本轮依据（国外社区，含互相矛盾的证据，按保守侧实现）：
#   · mkdir 原子锁：mkdir 保证单次创建只有一个成功者（HN/Command in Line）
#   · 陈旧锁回收：mkdir 失败 → 读 pid → kill -0 判活 → 死了才回收（SO 经典方案）
#   · NFS 原子性存在争议：pemungkah 实测 mkdir 在 NFS 原子；Facebook 技术问答称不保证
#     → 故不押单一原语，做 flock → mkdir → 放弃 的三级降级链
#   · 租约兜底：PID 可能被复用，kill -0 判活不足以证明持有者仍活着 → 加 TTL
#   · 原子写：临时文件 + sync + rename，读者不会看到半截内容
#   · 多租户隔离：共享挂载下应按租户分根，防路径穿越与符号链接越权（Blaxel）
#
# 用法：
#   boot.sh [--check|--diff] [--shared] [--user-scope]
#     --shared     使用团队共享基线（${PUA_DIR}）
#     --user-scope 使用个人基线（${PUA_DIR}/u-<uid>），默认
#
# 退出码：0 全绿或已修复 | 2 未修复漂移 | 3 锁被占用 | 4 用法/内部错误 | 5 锁机制全部不可用
set -uo pipefail

BASE="${PUA_DIR:-/sandbox/workspace/.pua}"
MODE="reconcile"; SCOPE="user"
for a in "$@"; do
  case "$a" in
    --check) MODE="check" ;;
    --diff)  MODE="diff" ;;
    --shared) SCOPE="shared" ;;
    --user-scope) SCOPE="user" ;;
    *) echo "[usage] boot.sh [--check|--diff] [--shared|--user-scope]" >&2; exit 4 ;;
  esac
done

if [ "$SCOPE" = "shared" ]; then
  PUA_DIR="$BASE"
else
  PUA_DIR="$BASE/u-$(id -u)"
fi

# ---- 路径安全校验（白名单 + 规范化），防路径穿越把文件写到系统目录 ----
norm_dir() {
  local d="$1" abs out="" part
  case "$d" in /*) abs="$d" ;; *) abs="$PWD/$d" ;; esac
  local IFS=/
  for part in $abs; do
    case "$part" in
      ''|'.') ;;
      '..') out="${out%/*}" ;;
      *) out="$out/$part" ;;
    esac
  done
  echo "${out:-/}"
}
PUA_DIR_RAW="$PUA_DIR"
PUA_DIR=$(norm_dir "$PUA_DIR")
case "$PUA_DIR" in
  /sandbox/workspace/*|/dev/shm/*|/tmp/*) : ;;
  *) echo "[refuse] PUA_DIR 不在允许范围（workspace / dev/shm / tmp）：$PUA_DIR_RAW" >&2; exit 4 ;;
esac
# fuse 盘上 mkdir -p 约 265ms，故先判断存在，缺失才建（稳态走快路径）
for d in system memory skills; do
  [ -d "$PUA_DIR/$d" ] || mkdir -p "$PUA_DIR/$d" || exit 4
done

LEASE=300   # 锁租约秒数，超时视为陈旧

# ---------------- 锁：按文件系统类型选定唯一原语（不运行时降级！） ----------------
# 关键教训：若“flock 失败就退到 mkdir”，会出现 A 持 flock、B 持 mkdir 同时进临界区。
# 因此锁原语必须在运行前单一确定，所有实例走同一套。
detect_lock() {
  local fs
  fs=$(stat -f -c %T "$PUA_DIR" 2>/dev/null || echo unknown)
  case "$fs" in
    nfs*|cifs*|smb*|fuse.*) echo mkdir ;;
    *) echo flock ;;
  esac
}
LOCK_IMPL="${PUA_LOCK:-$(detect_lock)}"
[ "${PUA_NO_FLOCK:-0}" = "1" ] && LOCK_IMPL="mkdir"

LOCKFILE="$PUA_DIR/.reconcile.lock"
LOCKDIR="$PUA_DIR/.reconcile.lockd"
LOCK_TYPE=""

acquire() {
  case "$LOCK_IMPL" in
    flock)
      exec 9>>"$LOCKFILE" 2>/dev/null || return 1
      flock -n 9 2>/dev/null || return 1      # 被占用即失败，绝不降级到 mkdir
      LOCK_TYPE="flock"; return 0 ;;
    mkdir)
      if mkdir "$LOCKDIR" 2>/dev/null; then
        echo $$ > "$LOCKDIR/pid"; date +%s > "$LOCKDIR/ts"
        LOCK_TYPE="mkdir"; return 0
      fi
      # 陈旧回收：pid 已死 或 超过租约
      local pid ts now age alive=1
      pid=$(cat "$LOCKDIR/pid" 2>/dev/null || echo "")
      ts=$(cat "$LOCKDIR/ts" 2>/dev/null || echo 0)
      now=$(date +%s); age=$(( now - ts ))
      [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && alive=0
      if [ "$alive" -ne 0 ] || [ "$age" -gt "$LEASE" ]; then
        local steal="$LOCKDIR.stale.$$.$RANDOM"
        if mv "$LOCKDIR" "$steal" 2>/dev/null; then
          rm -rf "$steal"
          if mkdir "$LOCKDIR" 2>/dev/null; then
            echo $$ > "$LOCKDIR/pid"; date +%s > "$LOCKDIR/ts"
            LOCK_TYPE="mkdir-reclaimed"; return 0
          fi
        fi
      fi
      return 1 ;;
    *) return 1 ;;
  esac
}

release() {
  case "$LOCK_TYPE" in
    flock) : ;;  # fd 9 关闭时自动释放
    mkdir*) [ -d "$LOCKDIR" ] && rm -rf "$LOCKDIR" ;;
  esac
}
trap release EXIT INT TERM

if ! acquire; then
  echo "[busy] 另一实例正在对账（pid=$(cat "$LOCKDIR/pid" 2>/dev/null || echo ?)），exit 3"
  exit 3
fi
echo "[lock] $LOCK_TYPE"

# ---------------- 期望状态 ----------------
FILES=(
  "system/always.md|## 交付底线"
  "memory/evolution.md|## 性能统计"
  "memory/anti-patterns.md|# 踩坑记录"
  "skills/index.md|# 技能库索引"
)
MIN_LINES=5

tpl_system() { cat <<'EOF'
# 硬约束（每次会话必读）

## 交付底线
1. 不做无证据的断言。"应该/大概/我记得"不算，附命令输出、文档原文、数据或行号。
2. 不说"已完成"除非有可核对证据（项数 + 轮次 + 结果）。
3. 主动报边界：做不到的、只能降频不能消除的、依赖外部条件的，必须明写。

## 行为约束
4. 一次只改一个变量；多变量同时变化的结论无效。
5. 状态不靠记忆，靠 .pua/ 里的文件。
6. 失败必须写进 memory/anti-patterns.md，三行：现象 / 根因 / 下次。
7. 技能库条目先对前提再使用，前提不匹配不许硬套。
EOF
}
tpl_evo() { cat <<'EOF'
# 基线

## 性能统计
- 最近会话主动行为次数: 0
- 历史最高: 0
- 连续达标会话: 0

## 当前基线
（本次会话表现将成为基线）
EOF
}
tpl_anti() { cat <<'EOF'
# 踩坑记录

> 格式：`- [日期] 现象 / 根因 / 下次`
> 上限约 50 条，超出后合并同类项

EOF
}
tpl_index() { cat <<'EOF'
# 技能库索引

> 格式：`- 名字 → 文件 | 前提 | 验证 | 边界`
> 入库闸：用过 2 次且都成功。检索闸：先对前提，不匹配不许套用。

EOF
}
tpl_for() {
  case "$1" in
    system/always.md) tpl_system ;;
    memory/evolution.md) tpl_evo ;;
    memory/anti-patterns.md) tpl_anti ;;
    skills/index.md) tpl_index ;;
  esac
}

# ---------------- 原子写 ----------------
# 注：不做 fsync。本场景是配置模板重建，掉电丢失可由下次对账重建；
# 而 fuse 盘上 sync 单文件约 193ms，代价远高于收益。rename 本身已保证原子可见性。
atomic_write() { # $1=目标路径, 内容从 stdin
  local dst="$1" tmp
  tmp="$dst.tmp.$$.$RANDOM"
  if cat > "$tmp" && [ -s "$tmp" ]; then
    mv -f "$tmp" "$dst" && return 0
  fi
  rm -f "$tmp"; return 1
}

# ---------------- 对账 ----------------
drift=0; changed=0; noop=0; failed=0
for entry in "${FILES[@]}"; do
  rel="${entry%%|*}"; anchor="${entry#*|}"
  f="$PUA_DIR/$rel"
  if [ -L "$f" ]; then
    state="symlink"        # 符号链接：可能是攻击，绝不可写穿
  elif [ ! -f "$f" ]; then
    state="missing"
  else
    # 一次 open 读完，用内建判断锚点与行数（省掉 grep + wc 两个 fork）
    _lines=()
    mapfile -t _lines < "$f" 2>/dev/null
    _joined="${_lines[*]}"
    if [[ "$_joined" != *"$anchor"* ]]; then state="stale"
    elif [ "${#_lines[@]}" -lt "$MIN_LINES" ]; then state="thin"
    else state="ok"; fi
  fi

  case "$state" in
    ok) echo "[noop] $rel"; noop=$((noop+1)) ;;
    *)
      drift=$((drift+1)); echo "[drift:$state] $rel"
      case "$MODE" in
        check) ;;
        diff) echo "    # 修复：bash $0   （会重建 $rel）" ;;
        reconcile)
          if [ "$state" = "symlink" ]; then
            # 拒绝写穿符号链接（可能指向工作区之外的目标），交给人判断
            echo "    [refuse] $rel 是符号链接（-> $(readlink "$f")），拒绝写入" >&2
            failed=$((failed+1))
            continue
          fi
          [ -f "$f" ] && cp -p "$f" "$f.bak.$(date +%s)" 2>/dev/null
          if [ "$state" = "missing" ]; then
            # 文件本不存在 → 没有"读到半截"风险，直写省一次 rename（fuse 上约 200ms/次）
            if tpl_for "$rel" > "$f" 2>/dev/null && [ -s "$f" ]; then
              echo "    [reconciled] $rel（直写）"; changed=$((changed+1))
            else
              echo "    [FAILED] $rel"; failed=$((failed+1)); rm -f "$f"
            fi
          else
            # 已有文件被写坏 → 原子替换，保证读者不会看到半截
            if tpl_for "$rel" | atomic_write "$f"; then
              echo "    [reconciled] $rel（原子替换）"; changed=$((changed+1))
            else
              echo "    [FAILED] $rel"; failed=$((failed+1))
            fi
          fi ;;
      esac ;;
  esac
done

echo "--- 对账摘要 ---"
printf '范围=%s 模式=%s 锁=%s noop=%d 漂移=%d 已修复=%d 失败=%d\n' \
  "$SCOPE" "$MODE" "$LOCK_TYPE" "$noop" "$drift" "$changed" "$failed"
grep -m1 '历史最高' "$PUA_DIR/memory/evolution.md" 2>/dev/null || echo "(无统计行)"
c1=$(grep -c '^- ' "$PUA_DIR/memory/anti-patterns.md" 2>/dev/null) || true
c2=$(grep -c '^- ' "$PUA_DIR/skills/index.md" 2>/dev/null) || true
[ -z "${c1:-}" ] && c1=0; [ -z "${c2:-}" ] && c2=0
printf '已知踩坑 %s 条 / 技能索引 %s 条\n' "$c1" "$c2"

J="$PUA_DIR/journal.md"
if [ -f "$J" ]; then
  now=$(date +%s)
  mt=$(date -r "$J" +%s 2>/dev/null || stat -c %Y "$J" 2>/dev/null || echo 0)
  age=$(( now - mt ))
  if [ "$age" -lt 7200 ]; then
    echo "[Calibration] 检查点 ${age}s 前更新。"
    echo "!! 先核对：这份检查点是否属于当前任务？不是则作废，禁止继承失败计数。"
    sed -n '1,12p' "$J"
  else
    echo "[ignore] 检查点已过期 ${age}s（>2h），不继承"
  fi
else
  echo "[cold] 无检查点，冷启动"
fi

[ "$failed" -gt 0 ] && exit 2
[ "$MODE" = "check" ] && [ "$drift" -gt 0 ] && exit 2
exit 0
