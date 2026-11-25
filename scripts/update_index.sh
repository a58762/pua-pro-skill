#!/usr/bin/env bash
# 每日增量更新本地索引：抓源 → 抓正文 → 生成向量
# 用法：bash scripts/update_index.sh
# 挂 cron 示例：0 7 * * * bash /path/to/scripts/update_index.sh >> /tmp/pua_index.log 2>&1
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONPATH="/opt/toolchain/pylibs${PYTHONPATH:+:$PYTHONPATH}"

echo "[$(date '+%F %T')] 开始更新索引"
python3 -u scripts/local_search.py index --fetch-body --body-limit "${BODY_LIMIT:-8}" --workers "${WORKERS:-12}"
python3 -u scripts/local_search.py embed
python3 -u scripts/local_search.py stats
echo "[$(date '+%F %T')] 完成"
