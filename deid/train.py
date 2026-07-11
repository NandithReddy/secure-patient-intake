"""Fine-tune a token classifier for PHI detection.

    python -m deid.train --out models/deid-deberta --epochs 4

Defaults to synthetic data so it runs today. Point `--data n2c2 --n2c2-dir
<path>` at the real corpus once your DUA clears.

Class weighting
---------------
PHI tokens are perhaps 8% of a clinical note, so a model that predicts O
everywhere scores 92% token accuracy and leaks 100% of the PHI. We weight the O
class down, which trades precision for recall — the correct direction for this
problem, and the same asymmetry the metrics module argues for. `--o-weight`
controls it; 0.3 is a reasonable starting point.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import O_CLASS_WEIGHT
from .redactors.transformer import DEFAULT_MODEL, label_list, spans_to_bio
from .types import Note


def _encode(notes: list[Note], tokenizer, label_to_id: dict[str, int],
            window: int, stride: int) -> list[dict]:
    features: list[dict] = []
    for note in notes:
        enc = tokenizer(
            note.text,
            return_offsets_mapping=True,
            return_overflowing_tokens=True,
            max_length=window,
            stride=stride,
            truncation=True,
            padding="max_length",
        )
        for i in range(len(enc["input_ids"])):
            seq_ids = enc.sequence_ids(i)
            offsets = [tuple(o) for o in enc["offset_mapping"][i]]
            features.append(
                {
                    "input_ids": enc["input_ids"][i],
                    "attention_mask": enc["attention_mask"][i],
                    "labels": spans_to_bio(note.spans, offsets, seq_ids, label_to_id),
                }
            )
    return features


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fine-tune the PHI token classifier")
    p.add_argument("--base-model", default=DEFAULT_MODEL)
    p.add_argument("--out", default="models/deid-deberta")
    p.add_argument("--data", choices=["synthetic", "n2c2"], default="synthetic")
    p.add_argument("--n2c2-dir", type=Path, default=None)
    p.add_argument("--epochs", type=float, default=4.0)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--lr", type=float, default=3e-5)
    p.add_argument("--window", type=int, default=512)
    p.add_argument("--stride", type=int, default=128)
    p.add_argument("--o-weight", type=float, default=O_CLASS_WEIGHT,
                   help="Loss weight for the O class. <1 favours recall.")
    p.add_argument("--n-synth", type=int, default=600)
    p.add_argument("--use-cpu", action="store_true",
                   help="Force CPU. Some models produce NaN under MPS.")
    args = p.parse_args(argv)

    import numpy as np
    import torch
    from torch import nn
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    if args.data == "n2c2":
        if not args.n2c2_dir:
            p.error("--data n2c2 requires --n2c2-dir")
        from .loaders.n2c2 import load_n2c2
        notes = load_n2c2(args.n2c2_dir)
        n_train = int(len(notes) * 0.8)
        train_notes, dev_notes = notes[:n_train], notes[n_train:]
    else:
        from .synth import generate_corpus, split
        train_notes, dev_notes, _ = split(generate_corpus(args.n_synth))

    labels = label_list()
    label_to_id = {l: i for i, l in enumerate(labels)}
    id_to_label = {i: l for l, i in label_to_id.items()}

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    if not tokenizer.is_fast:
        raise SystemExit(
            f"{args.base_model} has no fast tokenizer; offset mapping is required."
        )

    train_features = _encode(train_notes, tokenizer, label_to_id, args.window, args.stride)
    dev_features = _encode(dev_notes, tokenizer, label_to_id, args.window, args.stride)
    print(f"train windows: {len(train_features)}  dev windows: {len(dev_features)}")

    model = AutoModelForTokenClassification.from_pretrained(
        args.base_model,
        num_labels=len(labels),
        id2label=id_to_label,
        label2id=label_to_id,
    )

    class_weights = torch.ones(len(labels))
    class_weights[0] = args.o_weight

    class RecallWeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            lbls = inputs.pop("labels")
            outputs = model(**inputs)
            logits = outputs.logits
            # Match dtype as well as device: under autocast (MPS/CUDA) the logits
            # are fp16 while the weight tensor is fp32, and CrossEntropyLoss
            # rejects the mismatch with "expected scalar type Half but found Float".
            weight = class_weights.to(device=logits.device, dtype=logits.dtype)
            loss_fn = nn.CrossEntropyLoss(weight=weight, ignore_index=-100)
            loss = loss_fn(logits.view(-1, len(labels)), lbls.view(-1))
            inputs["labels"] = lbls
            return (loss, outputs) if return_outputs else loss

    def compute_metrics(eval_pred):
        """Token-level recall on PHI tokens — the number that matters here."""
        logits, gold = eval_pred
        preds = np.argmax(logits, axis=-1)
        mask = gold != -100
        gold_phi = mask & (gold != 0)
        pred_phi = mask & (preds != 0)
        tp = int((gold_phi & pred_phi & (preds == gold)).sum())
        detected = int((gold_phi & pred_phi).sum())  # right place, maybe wrong category
        n_gold = int(gold_phi.sum())
        n_pred = int(pred_phi.sum())
        return {
            "phi_token_recall": detected / n_gold if n_gold else 0.0,
            "phi_token_precision": detected / n_pred if n_pred else 0.0,
            "exact_label_recall": tp / n_gold if n_gold else 0.0,
        }

    out = Path(args.out)
    trainer = RecallWeightedTrainer(
        model=model,
        args=TrainingArguments(
            output_dir=str(out / "checkpoints"),
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch_size,
            per_device_eval_batch_size=args.batch_size,
            learning_rate=args.lr,
            # Half precision on MPS drives the eval loss to NaN on this model.
            # Training is minutes on a small corpus; full precision costs little.
            fp16=False,
            bf16=False,
            use_cpu=args.use_cpu,
            eval_strategy="epoch",
            save_strategy="epoch",
            load_best_model_at_end=True,
            metric_for_best_model="phi_token_recall",
            greater_is_better=True,
            logging_steps=25,
            report_to=[],
        ),
        train_dataset=train_features,
        eval_dataset=dev_features,
        compute_metrics=compute_metrics,
    )
    trainer.train()

    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    tokenizer.save_pretrained(out)
    print(f"\nSaved to {out}")
    print(f"Evaluate it:  python -m deid.cli eval --redactor transformer --model-dir {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
