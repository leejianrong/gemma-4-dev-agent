#!/usr/bin/env python3
"""LoRA on the E4B base from teacher trajectories (docs/research/lora-pod-plan.md).

Runs in ~/gpu-work/train-venv, never the vLLM venv. A GPU run goes through pueue only
(`python scripts/gpu_queue.py add ...`). Data is local and synthetic (rules 4b).

  lora_train.py check DATA_DIR MODEL_DIR            CPU: render records, report mask and lengths
  lora_train.py train DATA_DIR MODEL_DIR OUT_DIR [--smoke] [--edit-only] [--epochs N] [--rank R]
                [--lr X]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

MAX_LEN = 9000  # longer examples overflow a 16 GB card and thrash; median record is 5.8k tokens


def load(data_dir: Path, split: str) -> list[dict]:
    rows = [json.loads(line) for line in (data_dir / "train.jsonl").open()]
    return [r for r in rows if r["meta"]["split"] == split]


def template_view(msgs: list[dict]) -> list[dict]:
    """The messages as vLLM hands them to the chat template: tool-call arguments are dicts.

    A JSON string would render as `call:f{{"a": 1}}`, not the native `call:f{a:<|"|>1<|"|>}` the
    server's tool parser reads (the first adapter learned that and every call failed).
    """
    out = []
    for m in msgs:
        calls = m.get("tool_calls")
        if calls:
            m = {
                **m,
                "tool_calls": [
                    {
                        **c,
                        "function": {
                            **c["function"],
                            "arguments": json.loads(c["function"]["arguments"]),
                        },
                    }
                    for c in calls
                ],
            }
        out.append(m)
    return out


def _text(tok, msgs, tools, gen: bool) -> str:
    return tok.apply_chat_template(
        template_view(msgs), tools=tools, tokenize=False, add_generation_prompt=gen
    )


EDIT_TOOLS = {"edit_file", "write_file", "submit_patch"}


def loss_turns(msgs: list[dict], edit_only: bool) -> list[int]:
    """Indices of the assistant turns that carry loss.

    edit_only keeps just the edit and submit calls (A66: that made the model edit blind at call 1).
    """
    out = []
    for i, m in enumerate(msgs):
        if m["role"] != "assistant":
            continue
        names = {c["function"]["name"] for c in m.get("tool_calls") or []}
        if not edit_only or (names and names <= EDIT_TOOLS):
            out.append(i)
    return out


def build_example(tok, rec: dict, edit_only: bool = False) -> dict | None:
    """Token ids and labels for one record; labels are -100 everywhere but the assistant turns.

    Turn i is the text of messages[: i+1] after the text of messages[:i] plus the generation
    prompt, so the loss covers exactly what the model must write (the call or the answer).
    """
    msgs, tools = rec["messages"], rec["tools"]
    full = _text(tok, msgs, tools, False)
    spans: list[tuple[int, int]] = []
    for i in loss_turns(msgs, edit_only):
        head = _text(tok, msgs[:i], tools, True)
        upto = _text(tok, msgs[: i + 1], tools, False)
        if not (upto.startswith(head) and full.startswith(upto)):
            return None  # the template rewrites earlier text: cannot mask this record
        spans.append((len(head), len(upto)))
    enc = tok(full, add_special_tokens=False, return_offsets_mapping=True)
    ids = enc["input_ids"]
    labels = [-100] * len(ids)
    for k, (a, b) in enumerate(enc["offset_mapping"]):
        if any(s <= a and b <= e for s, e in spans):
            labels[k] = ids[k]
    return {"input_ids": ids, "labels": labels}


def check(data_dir: Path, model_dir: Path) -> int:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_dir)
    bad = over = 0
    lens, shares = [], []
    for split in ("train", "val"):
        for rec in load(data_dir, split):
            ex = build_example(tok, rec)
            if ex is None:
                bad += 1
                continue
            n = len(ex["input_ids"])
            lens.append(n)
            over += n > MAX_LEN
            shares.append(sum(x != -100 for x in ex["labels"]) / n)
    lens.sort()
    print(
        json.dumps(
            {
                "records": len(lens) + bad,
                "unmaskable": bad,
                "over_max_len": over,
                "tokens_median": lens[len(lens) // 2],
                "tokens_max": lens[-1],
                "loss_share_median": round(sorted(shares)[len(shares) // 2], 3),
            }
        )
    )
    return 1 if bad else 0


GROUP = 32  # the checkpoint's quantisation group size (config.json: group_size)
TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


def _dequant(packed, scale, shape):
    from compressed_tensors.compressors.pack_quantized.helpers import unpack_from_int32

    q = unpack_from_int32(packed, 4, shape)  # int8 (out, in), symmetric
    return q.to(scale.dtype) * scale.repeat_interleave(GROUP, dim=1)


def _make_layer_classes():
    import torch

    class QLinearFn(torch.autograd.Function):
        """x @ W.T with W dequantised on the fly; backward re-dequantises, so W is never kept."""

        @staticmethod
        def forward(ctx, x, packed, scale, shape):
            ctx.save_for_backward(packed, scale)
            ctx.shape = shape
            return x @ _dequant(packed, scale, shape).to(x.dtype).T

        @staticmethod
        def backward(ctx, g):
            packed, scale = ctx.saved_tensors
            return g @ _dequant(packed, scale, ctx.shape).to(g.dtype), None, None, None

    class LoraQLinear(torch.nn.Module):
        def __init__(self, base, rank: int, alpha: int):
            super().__init__()
            self.shape = torch.Size(base.weight_shape.tolist())
            self.register_buffer("packed", base.weight_packed.data, persistent=False)
            self.register_buffer("scale", base.weight_scale.data, persistent=False)
            out_f, in_f = self.shape
            dev = base.weight_packed.device
            self.lora_A = torch.nn.Parameter(
                torch.empty(rank, in_f, dtype=torch.float32, device=dev)
            )
            self.lora_B = torch.nn.Parameter(
                torch.zeros(out_f, rank, dtype=torch.float32, device=dev)
            )
            torch.nn.init.kaiming_uniform_(self.lora_A, a=5**0.5)
            self.scaling = alpha / rank

        def forward(self, x):
            y = QLinearFn.apply(x, self.packed, self.scale, self.shape)
            delta = (x.float() @ self.lora_A.T) @ self.lora_B.T
            return y + (delta * self.scaling).to(y.dtype)

    class FrozenQLinear(torch.nn.Module):
        """A quantised linear we do not adapt (per-layer projections): dequantise, no LoRA."""

        def __init__(self, base):
            super().__init__()
            self.shape = torch.Size(base.weight_shape.tolist())
            self.register_buffer("packed", base.weight_packed.data, persistent=False)
            self.register_buffer("scale", base.weight_scale.data, persistent=False)

        def forward(self, x):
            return QLinearFn.apply(x, self.packed, self.scale, self.shape)

    return LoraQLinear, FrozenQLinear


def inject_lora(model, rank: int, alpha: int) -> dict:
    """Swap every packed linear for a dequantising layer, with LoRA on the text model's
    attention and MLP projections; returns full module name -> LoRA layer."""
    import torch

    lora_cls, frozen_cls = _make_layer_classes()
    layers, made = {}, {}
    for name, mod in list(model.named_modules(remove_duplicate=False)):
        if not (isinstance(mod, torch.nn.Linear) and hasattr(mod, "weight_packed")):
            continue
        parent, leaf = model.get_submodule(name.rsplit(".", 1)[0]), name.rsplit(".", 1)[-1]
        if id(mod) not in made:  # a module can sit under two parents: share one replacement
            if "language_model" in name and leaf in TARGETS:
                made[id(mod)] = layers[name] = lora_cls(mod, rank, alpha)
            else:
                made[id(mod)] = frozen_cls(mod)
        setattr(parent, leaf, made[id(mod)])
    return layers


def save_adapter(layers: dict, out_dir: Path, rank: int, alpha: int, base: str) -> None:
    """PEFT file layout (adapter_model.safetensors, adapter_config.json), bf16 as Kaggle expects."""
    import torch
    from safetensors.torch import save_file

    tensors = {}
    for name, layer in layers.items():
        key = f"base_model.model.{name}"
        tensors[f"{key}.lora_A.weight"] = (
            layer.lora_A.detach().to(torch.bfloat16).cpu().contiguous()
        )
        tensors[f"{key}.lora_B.weight"] = (
            layer.lora_B.detach().to(torch.bfloat16).cpu().contiguous()
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    save_file(tensors, str(out_dir / "adapter_model.safetensors"), metadata={"format": "pt"})
    cfg = {
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "r": rank,
        "lora_alpha": alpha,
        "lora_dropout": 0.0,
        "bias": "none",
        "target_modules": list(TARGETS),
        "base_model_name_or_path": base,
        "inference_mode": True,
        "use_rslora": False,
        "use_dora": False,
        "fan_in_fan_out": False,
    }
    (out_dir / "adapter_config.json").write_text(json.dumps(cfg, indent=1))


class _CpuLookup:
    """Keeps a big embedding table in host memory; ids go over, rows come back to the GPU."""

    def __new__(cls, emb):
        import torch

        emb = emb.to("cpu")

        class Lookup(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.emb = emb

            def forward(self, ids):
                return self.emb(ids.cpu()).to("cuda")

        return Lookup()


def train(argv: list[str]) -> int:
    import torch
    import torch.nn.functional as F
    from transformers import AutoModelForCausalLM, AutoTokenizer

    data_dir, model_dir, out_dir = map(Path, argv[:3])
    flag = lambda n, d: type(d)(argv[argv.index(n) + 1]) if n in argv else d  # noqa: E731
    epochs, rank, lr = flag("--epochs", 2), flag("--rank", 16), flag("--lr", 1e-4)
    smoke = "--smoke" in argv
    edit_only = "--edit-only" in argv
    tok = AutoTokenizer.from_pretrained(model_dir)
    data = [e for r in load(data_dir, "train") if (e := build_example(tok, r, edit_only))]
    data = [d for d in data if len(d["input_ids"]) <= MAX_LEN]
    if smoke:
        data, epochs = sorted(data, key=lambda d: -len(d["input_ids"]))[:3], 1
    print(f"examples {len(data)}, epochs {epochs}, rank {rank}, lr {lr}", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa"
    )
    model.requires_grad_(False)
    lm = model.model.language_model
    lm.embed_tokens_per_layer = _CpuLookup(lm.embed_tokens_per_layer)  # 5.6 GB of rows, 1 lookup
    layers = inject_lora(model, rank, 2 * rank)
    print(f"lora layers {len(layers)}", flush=True)
    params = [p for layer in layers.values() for p in (layer.lora_A, layer.lora_B)]
    print(f"trainable {sum(p.numel() for p in params) / 1e6:.1f}M", flush=True)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    softcap = model.config.get_text_config().final_logit_softcapping
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)
    accum = 8
    steps = max(1, epochs * len(data) // accum)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / 3) * max(0.1, 1 - s / steps)
    )
    rng = random.Random(0)

    def loss_of(ex):
        ids = torch.tensor([ex["input_ids"]], device="cuda")
        lab = torch.tensor(ex["labels"][1:], device="cuda")
        h = lm(input_ids=ids).last_hidden_state[0, :-1]
        keep = lab != -100  # only the assistant tokens need logits (262k vocab)
        logits = model.lm_head(h[keep]).float()
        if softcap:
            logits = softcap * torch.tanh(logits / softcap)
        return F.cross_entropy(logits, lab[keep])

    val = [e for r in load(data_dir, "val") if (e := build_example(tok, r, edit_only))]
    val = [d for d in val if len(d["input_ids"]) <= MAX_LEN][: 2 if smoke else None]

    def evaluate(tag):
        model.eval()
        with torch.no_grad():
            vl = [loss_of(e).item() for e in val]
        model.train()
        print(f"VAL {tag} loss {sum(vl) / max(1, len(vl)):.4f} over {len(vl)}", flush=True)

    evaluate("start")
    model.train()
    for ep in range(epochs):
        rng.shuffle(data)
        tot = 0.0
        for i, ex in enumerate(data):
            loss = loss_of(ex)
            if not torch.isfinite(loss):
                raise SystemExit(f"non-finite loss at epoch {ep} example {i}")
            (loss / accum).backward()
            tot += loss.item()
            if (i + 1) % accum == 0 or i + 1 == len(data):
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step()
                sched.step()
                opt.zero_grad()
            mem = torch.cuda.max_memory_allocated() / 2**30
            print(f"ep {ep} ex {i} loss {loss.item():.4f} mem {mem:.1f}G", flush=True)
        print(f"TRAIN ep {ep} mean loss {tot / len(data):.4f}", flush=True)
        evaluate(f"after ep {ep}")
    save_adapter(layers, out_dir, rank, 2 * rank, model_dir.parent.name)
    print("saved", out_dir, flush=True)
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check":
        raise SystemExit(check(Path(sys.argv[2]), Path(sys.argv[3])))
    if cmd == "train":
        raise SystemExit(train(sys.argv[2:]))
    print(__doc__)
    raise SystemExit(2)
