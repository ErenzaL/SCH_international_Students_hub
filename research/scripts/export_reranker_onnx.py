"""Export cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 to ONNX: fp32, graph-optimized fp32, and dynamic INT8.

Outputs (git-ignored, regenerable) in research/models/mminilm/:
  model_fp32.onnx       torch.onnx export (inputs input_ids, attention_mask; output logits [batch, 1])
  model_opt.onnx        onnxruntime transformer optimizer (attention / layer-norm / GELU fusion), fp32
  model_int8.onnx       onnxruntime dynamic quantization of model_opt.onnx (int8 weights, fp32 activations)
  sentencepiece.bpe.model, export_manifest.json
The tokenizer check compares the backend's SentencePiece pair encoding with the HF tokenizer on real benchmark
question/passage pairs (ids must be identical).

    research/.venv-rerank/bin/python research/scripts/export_reranker_onnx.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "research/scripts"))
REPO = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
OUT = ROOT / "research/models/mminilm"


def sha16(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def main() -> None:
    import torch
    from huggingface_hub import hf_hub_download
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    OUT.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(REPO)
    model = AutoModelForSequenceClassification.from_pretrained(REPO).eval()
    with torch.no_grad():                      # copy out of the safetensors memory map (SIGBUS guard, see reranking.py)
        for p in model.parameters():
            p.data = p.data.clone().contiguous()
    (OUT / "sentencepiece.bpe.model").unlink(missing_ok=True)
    shutil.copyfile(hf_hub_download(REPO, "sentencepiece.bpe.model"), OUT / "sentencepiece.bpe.model")

    fp32 = OUT / "model_fp32.onnx"
    enc = tok(["질문 예시"], ["예시 문단입니다."], return_tensors="pt", padding=True)

    class Wrapped(torch.nn.Module):
        def __init__(self, m):  # type: ignore[no-untyped-def]
            super().__init__()
            self.m = m

        def forward(self, input_ids, attention_mask):  # type: ignore[no-untyped-def]
            return self.m(input_ids=input_ids, attention_mask=attention_mask).logits

    t0 = time.perf_counter()
    torch.onnx.export(Wrapped(model), (enc["input_ids"], enc["attention_mask"]), str(fp32),
                      input_names=["input_ids", "attention_mask"], output_names=["logits"],
                      dynamic_axes={"input_ids": {0: "batch", 1: "seq"}, "attention_mask": {0: "batch", 1: "seq"},
                                    "logits": {0: "batch"}}, opset_version=17, dynamo=False)
    export_s = time.perf_counter() - t0

    from onnxruntime.quantization import QuantType, quantize_dynamic
    from onnxruntime.transformers.optimizer import optimize_model

    opt = OUT / "model_opt.onnx"
    om = optimize_model(str(fp32), model_type="bert", num_heads=12, hidden_size=384, opt_level=1)
    om.save_model_to_file(str(opt))
    fused = om.get_fused_operator_statistics()
    int8 = OUT / "model_int8.onnx"
    import onnx

    # fused nodes (com.microsoft domain) have no inferred output type: declare fp32 activations explicitly
    quantize_dynamic(str(opt), str(int8), weight_type=QuantType.QInt8,
                     extra_options={"DefaultTensorType": onnx.TensorProto.FLOAT})

    # tokenizer check: backend SentencePiece pair encoding == HF tokenizer ids
    from app.services.retrieval.rerank import encode_pair
    import sentencepiece as spm

    sp = spm.SentencePieceProcessor(model_file=str(OUT / "sentencepiece.bpe.model"))
    from jsonl_io import open_jsonl

    pairs = []
    for line in open_jsonl(ROOT / "research/data/results/corpus_v2/candidates_heldout_v0.2.jsonl"):
        r = json.loads(line)
        for c in r["E2"]["candidates"][:3]:
            head = (c.get("heading") or "").strip()
            pairs.append((r["question"], f"{head}\n{c.get('passage') or ''}" if head else (c.get("passage") or "")))
    same = 0
    for q, p in pairs:
        hf = tok(q, p, truncation=True, max_length=512)["input_ids"]
        same += hf == encode_pair(sp, q, p, 512)
    manifest = dict(repo=REPO, torch=torch.__version__, export_seconds=round(export_s, 1), opset=17,
                    files={f.name: dict(bytes=f.stat().st_size, sha256_16=sha16(f)) for f in (fp32, opt, int8)},
                    fused_operators={k: v for k, v in fused.items() if v},
                    tokenizer_check=dict(pairs=len(pairs), identical_ids=same))
    (OUT / "export_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
