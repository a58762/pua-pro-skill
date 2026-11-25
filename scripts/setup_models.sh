#!/usr/bin/env bash
# setup_models.sh —— 首次部署时下载本地检索所需的模型资产（技能本体不含大文件）
#
# 下载内容：
#   1. paraphrase-multilingual-MiniLM-L12-v2 ONNX (~450MB) —— 默认语义模型，50+ 语种
#   2. lightpanda 1.0.5 (~75MB)                            —— JS 渲染兜底（可选，缺了就自动跳过）
#   3. Qwen3-Embedding-0.6B int8 ONNX (~585MB)             —— 可选，仅当 PUA_WANT_QWEN3=1
#
# 用法：
#   bash scripts/setup_models.sh              # 必装项（MiniLM + lightpanda）
#   PUA_WANT_QWEN3=1 bash scripts/setup_models.sh   # 追加 Qwen3
set -u
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DL="$SKILL_DIR/scripts/dl_chunks.py"
PY="${PYTHON:-python3}"
MODELS="${PUA_MODELS_DIR:-$SKILL_DIR/models}"
HF="${HF_ENDPOINT:-https://hf-mirror.com}"
LP_DIR="${PUA_BIN_DIR:-$SKILL_DIR/bin}"
mkdir -p "$MODELS" "$LP_DIR"

echo "== 模型目录: $MODELS"

# ---------- 1. 多语言 MiniLM ----------
MINI="$MODELS/multilingual-minilm"
if [ ! -f "$MINI/model_optimized.onnx" ]; then
  mkdir -p "$MINI"
  echo "-- [1/3] 下载 MiniLM-multilingual (450MB)"
  "$PY" "$DL" "$HF/Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/resolve/main/model.onnx" \
      "$MINI/model_optimized.onnx" - 470301610 4 32 10 2>&1 | tail -2
  REV="$HF/Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/resolve/main"
  for f in config.json tokenizer.json tokenizer_config.json special_tokens_map.json; do
    curl -sL --max-time 120 -o "$MINI/$f" "$REV/$f" || true
  done
  echo "   完成: $MINI"
else
  echo "-- [1/3] MiniLM 已存在，跳过"
fi

# ---------- 2. lightpanda（JS 渲染）----------
if [ ! -x "$LP_DIR/lightpanda" ]; then
  case "$(uname -m)" in
    x86_64|amd64) LPA=lightpanda-x86_64-linux; LPN=78026056 ;;
    aarch64|arm64) LPA=lightpanda-aarch64-linux; LPN=77600000 ;;
    *) LPA=""; LPN=0 ;;
  esac
  if [ -n "$LPA" ]; then
    echo "-- [2/3] 下载 lightpanda (75MB) [$LPA]"
    "$PY" "$DL" "https://gh-proxy.com/https://github.com/lightpanda-io/browser/releases/download/1.0.5/$LPA" \
        "$LP_DIR/lightpanda" - "$LPN" 2 16 12 2>&1 | tail -2
    chmod +x "$LP_DIR/lightpanda" 2>/dev/null || true
    echo "   完成: $LP_DIR/lightpanda"
  else
    echo "-- [2/3] 当前架构不支持预编译 lightpanda，跳过（JS 站将无法渲染）"
  fi
else
  echo "-- [2/3] lightpanda 已存在，跳过"
fi

# ---------- 3. Qwen3-Embedding（可选）----------
if [ "${PUA_WANT_QWEN3:-0}" = "1" ]; then
  Q3="$MODELS/qwen3-emb-0.6b"
  if [ ! -f "$Q3/onnx/model_int8.onnx" ]; then
    mkdir -p "$Q3/onnx"
    echo "-- [3/3] 下载 Qwen3-Embedding-0.6B int8 (585MB)"
    Q3B="$HF/onnx-community/Qwen3-Embedding-0.6B-ONNX/resolve/main"
    "$PY" "$DL" "$Q3B/onnx/model_int8.onnx" "$Q3/onnx/model_int8.onnx" - 613527539 4 32 10 2>&1 | tail -2
    "$PY" "$DL" "$Q3B/tokenizer.json" "$Q3/tokenizer.json" - 11423705 2 8 6 2>&1 | tail -2
    for f in config.json tokenizer_config.json special_tokens_map.json; do
      curl -sL --max-time 120 -o "$Q3/$f" "$Q3B/$f" || true
    done
  fi
  echo "-- [3/3] Qwen3 就绪: $Q3"
else
  echo "-- [3/3] 跳过 Qwen3（需要时 PUA_WANT_QWEN3=1 bash scripts/setup_models.sh）"
fi

echo
echo "校验："
"$PY" - <<'PYCHK'
import os, sys
sys.path.insert(0, os.environ.get("SKILL_DIR", "") + "/scripts") if os.environ.get("SKILL_DIR") else None
base = os.environ.get("PUA_MODELS_DIR", "/sandbox/workspace/skills/pua-pro/models")
m = os.path.join(base, "multilingual-minilm", "model_optimized.onnx")
print(f"  MiniLM onnx: {'OK ' + str(os.path.getsize(m)//1048576) + 'MB' if os.path.exists(m) else '缺失'}")
for p in [os.environ.get("PUA_BIN_DIR", "/sandbox/workspace/skills/pua-pro/bin") + "/lightpanda"]:
    print(f"  lightpanda : {'OK ' + str(os.path.getsize(p)//1048576) + 'MB' if os.path.exists(p) else '缺失（JS 渲染不可用）'}")
PYCHK
