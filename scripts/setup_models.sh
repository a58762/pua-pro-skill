#!/usr/bin/env bash
# setup_models.sh —— 首次部署时下载本地检索所需的模型资产（技能本体不含大文件）
#
# 下载内容：
#   1. EmbeddingGemma-300m q4 ONNX (~197MB) —— 默认语义模型（Google，HF trending 榜首，本机实测 R@1=0.733）
#   2. lightpanda 1.0.5 (~75MB)             —— JS 渲染兜底（可选，缺了就自动跳过）
#   3. MiniLM-multilingual (~450MB)         —— 回退模型，仅当 PUA_WANT_MINILM=1
#
# 用法：
#   bash scripts/setup_models.sh                    # 默认：Harrier + lightpanda
#   PUA_WANT_MINILM=1 bash scripts/setup_models.sh  # 追加回退模型
set -u
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DL="$SKILL_DIR/scripts/dl_chunks.py"
PY="${PYTHON:-python3}"
MODELS="${PUA_MODELS_DIR:-$SKILL_DIR/models}"
HF="${HF_ENDPOINT:-https://hf-mirror.com}"
LP_DIR="${PUA_BIN_DIR:-$SKILL_DIR/bin}"
mkdir -p "$MODELS" "$LP_DIR"

# 统一下载函数：有 aria2c 用它（实测 17MB/s，比逐块下载快 6 倍），否则回退 dl_chunks
dl_one() {
  local url="$1" out="$2" size="$3"
  if command -v aria2c >/dev/null 2>&1; then
    aria2c -x16 -s16 -k4M -q --file-allocation=none -o "$(basename "$out")" -d "$(dirname "$out")" "$url" 2>&1 | tail -1
  else
    "$PY" "$DL" "$url" "$out" - "$size" 4 32 10 2>&1 | tail -2
  fi
}

echo "== 模型目录: $MODELS"

# ---------- 1. Harrier-OSS-V1-0.6B q4（主模型）----------
GM="$MODELS/embeddinggemma300"
if [ ! -f "$GM/onnx/model_q4.onnx_data" ]; then
  mkdir -p "$GM/onnx"
  echo "-- [1/3] 下载 EmbeddingGemma-300m q4 (197MB)"
  GB="$HF/onnx-community/embeddinggemma-300m-ONNX/resolve/main"
  dl_one "$GB/onnx/model_q4.onnx_data" "$GM/onnx/model_q4.onnx_data" 196725760
  dl_one "$GB/onnx/model_q4.onnx" "$GM/onnx/model_q4.onnx" 519322
  for f in config.json tokenizer.json tokenizer_config.json special_tokens_map.json; do
    curl -sL --max-time 120 -o "$GM/$f" "$GB/$f" || true
  done
  echo "   完成: $GM"
else
  echo "-- [1/3] EmbeddingGemma 已存在，跳过"
fi

HAR="$MODELS/harrier-0.6b"
if [ ! -f "$HAR/onnx/model_q4.onnx_data" ]; then
  mkdir -p "$HAR/onnx"
  echo "-- [1/3] 下载 Harrier-OSS-V1-0.6B q4 (399MB)"
  HB="$HF/onnx-community/harrier-oss-v1-0.6b-ONNX/resolve/main"
  "$PY" "$DL" "$HB/onnx/model_q4.onnx_data" "$HAR/onnx/model_q4.onnx_data" - 398813184 4 32 10 2>&1 | tail -2
  curl -sL --max-time 60 -o "$HAR/onnx/model_q4.onnx" "$HB/onnx/model_q4.onnx" || true
  for f in config.json tokenizer.json tokenizer_config.json special_tokens_map.json added_tokens.json modules.json; do
    curl -sL --max-time 120 -o "$HAR/$f" "$HB/$f" || true
  done
  echo "   完成: $HAR"
else
  echo "-- [1b/3] Harrier 已存在，跳过"
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

# ---------- 3. MiniLM（可选回退）----------
if [ "${PUA_WANT_MINILM:-0}" = "1" ]; then
  MINI="$MODELS/multilingual-minilm"
  if [ ! -f "$MINI/model_optimized.onnx" ]; then
    mkdir -p "$MINI"
    echo "-- [3/3] 下载 MiniLM-multilingual 回退模型 (450MB)"
    MB="$HF/Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q/resolve/main"
    "$PY" "$DL" "$MB/model.onnx" "$MINI/model_optimized.onnx" - 470301610 4 32 10 2>&1 | tail -2
    for f in config.json tokenizer.json tokenizer_config.json special_tokens_map.json; do
      curl -sL --max-time 120 -o "$MINI/$f" "$MB/$f" || true
    done
  fi
  echo "-- [3/3] MiniLM 就绪: $MINI"
else
  echo "-- [3/3] 跳过 MiniLM（PUA_WANT_MINILM=1 可装回退模型）"
fi

echo
echo "校验："
"$PY" - <<'PYCHK'
import os, sys
sys.path.insert(0, os.environ.get("SKILL_DIR", "") + "/scripts") if os.environ.get("SKILL_DIR") else None
base = os.environ.get("PUA_MODELS_DIR", "/sandbox/workspace/skills/pua-pro/models")
g = os.path.join(base, "embeddinggemma300", "onnx", "model_q4.onnx_data")
print(f"  Gemma-300m : {'OK ' + str(os.path.getsize(g)//1048576) + 'MB' if os.path.exists(g) else '缺失（主模型）'}")
h = os.path.join(base, "harrier-0.6b", "onnx", "model_q4.onnx_data")
print(f"  Harrier q4 : {'OK ' + str(os.path.getsize(h)//1048576) + 'MB' if os.path.exists(h) else '未安装'}")
m = os.path.join(base, "multilingual-minilm", "model_optimized.onnx")
print(f"  MiniLM(回退): {'OK ' + str(os.path.getsize(m)//1048576) + 'MB' if os.path.exists(m) else '未安装'}")
for p in [os.environ.get("PUA_BIN_DIR", "/sandbox/workspace/skills/pua-pro/bin") + "/lightpanda"]:
    print(f"  lightpanda : {'OK ' + str(os.path.getsize(p)//1048576) + 'MB' if os.path.exists(p) else '缺失（JS 渲染不可用）'}")
PYCHK
