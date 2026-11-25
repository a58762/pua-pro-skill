#!/usr/bin/env python3
"""Qwen3-Embedding-0.6B (int8 ONNX) 独立推理器。
fastembed 未收录该模型，故直接用 onnxruntime + tokenizers 跑：
  · decoder-only 架构 → 用最后一个 token 的隐状态做 pooling（官方用法）
  · L2 归一化后余弦相似度即点积
"""
import os
import sys
import numpy as np

D = os.environ.get("QWEN3_EMB_DIR", "/sandbox/workspace/models/qwen3-emb-0.6b")
F = os.environ.get("QWEN3_EMB_FILE", "model_int8.onnx")   # 可指向 harrier 的 model_q4.onnx
_sess = None
_tok = None


def _load():
    global _sess, _tok
    if _sess is not None:
        return
    import onnxruntime as ort
    from tokenizers import Tokenizer
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
    _tok.enable_padding(direction="left", pad_id=0, pad_token="<|endoftext|>")


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
        # 该 ONNX 是带 KV-cache 的解码版：空 past（past_len=0）即等价于纯前向
        for nm in names:
            if nm.startswith("past_key_values"):
                feed[nm] = np.zeros((n, 8, 0, 128), dtype=np.float32)
        res = _sess.run(None, feed)[0]
        if pre:
            v = res.astype("float32")             # 已是 (n, dim) 句向量
        else:
            v = res[:, -1].astype("float32")   # 左填充下最后一位必是真实 token
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
