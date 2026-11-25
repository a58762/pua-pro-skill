#!/usr/bin/env python3
"""Qwen3-Embedding-0.6B (int8 ONNX) 独立推理器。
fastembed 未收录该模型，故直接用 onnxruntime + tokenizers 跑：
  · decoder-only 架构 → 用最后一个 token 的隐状态做 pooling（官方用法）
  · L2 归一化后余弦相似度即点积
"""
import os
import sys
import numpy as np

# ⚠️ 这些必须在 _load() 里读，不能固化成模块级常量——
# 否则进程内切换模型（local_search 的 _GemmaWrapper / _HarrierWrapper）改环境变量无效
def _env_dir():
    return os.environ.get("QWEN3_EMB_DIR", "/sandbox/workspace/models/qwen3-emb-0.6b")


def _env_file():
    return os.environ.get("QWEN3_EMB_FILE", "model_int8.onnx")


D = _env_dir()
F = _env_file()
# pooling 策略：pre=模型已内置 | last=decoder-only(last-token) | mean=encoder(如 bge-m3 XLM-R)
# 留空则自动：有 past_key_values → last；只有一个 sentence_embedding 输出 → pre；否则 mean
def _env_pool():
    return os.environ.get("QWEN3_POOL", "")


def _env_pad():
    return os.environ.get("QWEN3_PAD", "left")
_sess = None
_tok = None


def _load():
    global _sess, _tok, POOL, PAD
    POOL, PAD = _env_pool(), _env_pad()
    if _sess is not None:
        return
    import onnxruntime as ort
    from tokenizers import Tokenizer
    global D, F
    D, F = _env_dir(), _env_file()
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    _p1, _p2 = os.path.join(D, "onnx", F), os.path.join(D, F)
    _mp = _p1 if os.path.isfile(_p1) else (_p2 if os.path.isfile(_p2) else _p1)
    _sess = ort.InferenceSession(_mp,
                                 sess_options=so, providers=["CPUExecutionProvider"])
    _tok = Tokenizer.from_file(os.path.join(D, "tokenizer.json"))
    _tok.enable_truncation(max_length=int(os.environ.get("QWEN3_MAXLEN", "512")))
    # decoder-only 模型的 last-token pooling 必须左填充：右填充会让"最后一个位置"落在 pad 上，
    # 取到 pad 的隐状态，向量全错（实测 batch=4 时 R@1 从 0.95 掉到 0.15）
    # pad token 自动探测：Qwen3 系是 <|endoftext|>，Gemma 是 <pad>，写死会直接算错
    import json as _json
    _pt, _pid = "<|endoftext|>", 0
    try:
        _cfg = _json.load(open(os.path.join(D, "tokenizer_config.json")))
        if _cfg.get("pad_token"):
            _pt = _cfg["pad_token"]
    except Exception:
        pass
    _pid = _tok.token_to_id(_pt)
    if _pid is None:
        _pid = 0
        _pt = _tok.id_to_token(0) or _pt
    if os.environ.get("QWEN3_NOPAD") != "1":
        _tok.enable_padding(direction=_env_pad(), pad_id=_pid, pad_token=_pt)


def _pre_pooled():
    """onnx-community 的某些导出已内置 pooling+normalize（输出 sentence_embedding）。
    这类模型输入只有 input_ids/attention_mask，直接用输出即可。"""
    outs = _sess.get_outputs()
    return len(outs) == 1 and "sentence_embedding" in outs[0].name


def embed(texts, batch=16):
    """返回 (N, dim) L2 归一化向量；自动适配「已 pooling」与「需自行 pooling」两种导出"""
    _load()
    names = {i.name for i in _sess.get_inputs()}
    pre = _pre_pooled()
    out = []
    for s in range(0, len(texts), batch):
        enc = _tok.encode_batch(texts[s:s + batch])
        n = len(enc)
        L = max(len(e.ids) for e in enc)
        ids = np.zeros((n, L), dtype=np.int64)
        mask = np.zeros((n, L), dtype=np.int64)
        for i, e in enumerate(enc):
            k = len(e.ids)
            ids[i, :k] = e.ids
            mask[i, :k] = 1
        feed = {"input_ids": ids, "attention_mask": mask}
        if "position_ids" in names:
            feed["position_ids"] = np.tile(np.arange(L, dtype=np.int64), (n, 1))
        # 多模态模型的空输入（embeddinggemma-2 的 image/video/audio 特征，纯文本任务传空）
        for nm in ("image_features", "video_features", "audio_features"):
            if nm in names:
                feed[nm] = np.zeros((1, 512), dtype=np.float32)
        # 该 ONNX 是带 KV-cache 的解码版：空 past（past_len=0）即等价于纯前向
        for nm in names:
            if nm.startswith("past_key_values"):
                feed[nm] = np.zeros((n, 8, 0, 128), dtype=np.float32)
        res = _sess.run(None, feed)[0]
        mode = _env_pool() or ("pre" if pre else ("last" if any(k.startswith("past_key_values") for k in names) else "mean"))
        if mode == "pre":
            v = res.astype("float32")             # 已是 (n, dim) 句向量
        elif mode == "last":
            v = res[:, -1].astype("float32")      # 左填充下最后一位必是真实 token
        elif mode == "cls":
            v = res[:, 0].astype("float32")       # 右填充下首位必是 CLS（XLM-R 的 <s>）
        else:                                     # mean：attention_mask 加权平均（encoder 模型）
            m = mask[..., None].astype("float32")
            v = (res * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        v /= (np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)
        out.append(v)
    return np.vstack(out)


if __name__ == "__main__":
    qs = ["大语言模型", "大規模言語モデル", "large language model",
          "开源软件的安全性", "open source software security", "Künstliche Intelligenz"]
    import time
    t = time.time()
    V = embed(qs)
    print(f"加载+{len(qs)}条: {time.time()-t:.1f}s  维度 {V.shape[1]}")
    S = V @ V.T
    print(f"中LLM vs 日大規模言語モデル: {S[0][1]:.3f}")
    print(f"中LLM vs 英large language model: {S[0][2]:.3f}")
    print(f"中开源安全 vs 英OSS security: {S[3][4]:.3f}")
    print(f"中LLM vs 德KI(不同义，应偏低): {S[0][5]:.3f}")
    print(f"日LLM vs 英LLM: {S[1][2]:.3f}")
