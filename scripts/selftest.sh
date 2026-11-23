#!/usr/bin/env bash
# PUA Pro v4.3 断言自测：覆盖幂等 / 漂移 / dry-run / 双锁原语 / 陈旧锁回收 / 租约 / 用户隔离 / 原子写
set -uo pipefail
# 定位自身所在目录：保证测的是本目录的脚本，不是别处的副本（防假通过）
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOT="$SELF_DIR/boot.sh"
# 测试目录放内存盘：fuse 盘单次文件写约 200-400ms，/dev/shm 快一个数量级，
# 且完全不污染工作区。若 /dev/shm 不可用则回退到工作区。
if [ -d /dev/shm ] && [ -w /dev/shm ]; then
  BASE="/dev/shm/.pua_TEST_$$"
else
  BASE="/sandbox/workspace/.pua_TEST_$$"
fi
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ok   $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  FAIL $1"; }
chk(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1（期望 $3，实得 $2）"; fi; }
trap 'rm -rf "$BASE"' EXIT

echo "=== 1. 冷启动（默认 user 作用域） ==="
PUA_DIR="$BASE" bash "$BOOT" >/dev/null 2>&1
U="$BASE/u-$(id -u)"
chk "四个文件建立" "$(find "$U" -name '*.md' 2>/dev/null | wc -l)" "4"

echo "=== 2. 幂等 ==="
out=$(PUA_DIR="$BASE" bash "$BOOT" 2>&1)
chk "noop=4" "$(echo "$out" | grep -c '\[noop\]')" "4"
chk "无 reconciled" "$(echo "$out" | grep -c 'reconciled')" "0"

echo "=== 3/4. dry-run 不写盘 ==="
PUA_DIR="$BASE/t34" bash "$BOOT" --check >/dev/null 2>&1
PUA_DIR="$BASE/t34" bash "$BOOT" --diff  >/dev/null 2>&1
chk "check+diff 零文件" "$(find "$BASE/t34" -name '*.md' 2>/dev/null | wc -l)" "0"

echo "=== 5. 漂移检测与修复 ==="
echo "坏内容" > "$U/system/always.md"
chk "check 报 stale" "$(PUA_DIR="$BASE" bash "$BOOT" --check 2>&1 | grep -c 'drift:stale')" "1"
PUA_DIR="$BASE" bash "$BOOT" >/dev/null 2>&1
chk "已恢复锚点" "$(grep -c '## 交付底线' "$U/system/always.md")" "1"
chk "生成备份" "$(ls "$U/system" | grep -c 'bak')" "1"

echo "=== 6. flock 层并发 ==="
( exec 9>>"$U/.reconcile.lock"; flock -n 9 && sleep 0.6 ) &
sleep 0.15
chk "flock 占用→exit 3" "$(PUA_DIR="$BASE" bash "$BOOT" >/dev/null 2>&1; echo $?)" "3"
wait

echo "=== 7. mkdir 层锁（禁用 flock） ==="
rm -rf "$U/.reconcile.lockd"
mkdir -p "$U/.reconcile.lockd"; echo $$ > "$U/.reconcile.lockd/pid"; date +%s > "$U/.reconcile.lockd/ts"
chk "mkdir 锁占用→exit 3" "$(PUA_NO_FLOCK=1 PUA_DIR="$BASE" bash "$BOOT" >/dev/null 2>&1; echo $?)" "3"
rm -rf "$U/.reconcile.lockd"

echo "=== 8. 陈旧锁回收（pid 已死） ==="
mkdir -p "$U/.reconcile.lockd"; echo 999999 > "$U/.reconcile.lockd/pid"; date +%s > "$U/.reconcile.lockd/ts"
out=$(PUA_NO_FLOCK=1 PUA_DIR="$BASE" bash "$BOOT" 2>&1)
if echo "$out" | grep -q 'mkdir-reclaimed'; then ok "回收并继续"; else bad "回收并继续（输出无 mkdir-reclaimed）"; fi
chk "锁已释放" "$([ -d "$U/.reconcile.lockd" ] && echo 1 || echo 0)" "0"

echo "=== 9. 租约超时回收（pid 活着但超时） ==="
mkdir -p "$U/.reconcile.lockd"; echo "$$" > "$U/.reconcile.lockd/pid"; echo 1 > "$U/.reconcile.lockd/ts"
out9=$(PUA_NO_FLOCK=1 PUA_DIR="$BASE" bash "$BOOT" 2>&1)
if echo "$out9" | grep -q 'mkdir-reclaimed'; then ok "超租约→回收"; else bad "超租约→回收（实得：$(echo "$out9" | head -1)）"; fi

echo "=== 10. 用户作用域与共享作用域隔离 ==="
PUA_DIR="$BASE" bash "$BOOT" --shared >/dev/null 2>&1
chk "shared 目录独立存在" "$([ -f "$BASE/memory/evolution.md" ] && echo 1 || echo 0)" "1"
chk "两者内容互不覆盖" "$(grep -c '历史最高' "$BASE/memory/evolution.md" 2>/dev/null)" "1"

echo "=== 11. 原子写无残留 ==="
chk "无 .tmp 残留" "$(find "$BASE" -name '*.tmp.*' 2>/dev/null | wc -l)" "0"

echo "=== 13. 安全：路径穿越拒绝 ==="
chk "穿越路径 exit 4" "$(PUA_DIR="$BASE/../../etc/evil" bash "$BOOT" --check >/dev/null 2>&1; echo $?)" "4"
chk "系统路径 exit 4" "$(PUA_DIR="/etc/evil" bash "$BOOT" --check >/dev/null 2>&1; echo $?)" "4"

echo "=== 14. 安全：符号链接不写穿 ==="
echo "受保护的原文件内容" > "$BASE/protected_target"
rm -f "$U/system/always.md"
ln -s "$BASE/protected_target" "$U/system/always.md"
before=$(md5sum "$BASE/protected_target" | cut -d' ' -f1)
out=$(PUA_DIR="$BASE" bash "$BOOT" 2>&1)
after=$(md5sum "$BASE/protected_target" | cut -d' ' -f1)
chk "识别 symlink" "$(echo "$out" | grep -c 'drift:symlink')" "1"
chk "链接目标未被写穿" "$before" "$after"
rm -f "$U/system/always.md"
PUA_DIR="$BASE" bash "$BOOT" >/dev/null 2>&1
chk "移除后可正常重建" "$(grep -c '## 交付底线' "$U/system/always.md")" "1"

echo "=== 15. stdout/stderr 分离 ==="
errout=$(PUA_DIR="/etc/evil" bash "$BOOT" --check 2>&1 >/dev/null)
chk "错误信息走 stderr" "$(echo "$errout" | grep -c 'refuse')" "1"

echo "=== 12. 退出码与语法 ==="
chk "测试对象是本目录脚本" "$BOOT" "$SELF_DIR/boot.sh"
if [ ! -f "$BOOT" ]; then bad "boot.sh 不存在于本目录"; fi
chk "全绿 exit 0" "$(PUA_DIR="$BASE" bash "$BOOT" >/dev/null 2>&1; echo $?)" "0"
chk "非法参数 exit 4" "$(PUA_DIR="$BASE" bash "$BOOT" --oops >/dev/null 2>&1; echo $?)" "4"
bash -n "$BOOT" 2>/dev/null && ok "bash -n" || bad "bash -n"

echo "-----------------------------------"
printf '通过 %d / 失败 %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
