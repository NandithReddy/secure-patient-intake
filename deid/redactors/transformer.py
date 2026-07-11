"""Transformer token-classification redactor. This is the production path.

It runs entirely on your machine. No note text ever leaves the process. That is
not an incidental property — it is the whole architectural argument of this
project, and it is why this redactor, not the LLM one, is what the service
calls.

Implementation notes
--------------------
BIO tagging over subword tokens, decoded back to character offsets via the fast
tokenizer's `offset_mapping`. Two details that are easy to get wrong:

1. **Long notes.** Clinical notes routinely exceed the model's 512-token
   window. We use overflowing tokens with a stride so the windows overlap; a
   span straddling a window boundary is caught by the neighbouring window.
   Truncating instead would silently drop PHI from the tail of every long note
   — a failure that looks like a great precision score.

2. **Special tokens.** [CLS]/[SEP] carry offset (0, 0). Filtering on
   `offset != (0, 0)` would also throw away a real token at position 0, which
   in these notes is the first character of the header. We use the tokenizer's
   `sequence_ids()` instead, which is unambiguous.
"""

from __future__ import annotations

from pathlib import Path

from ..config import BASE_MODEL
from ..types import PhiCategory, PhiSpan
from .base import BaseRedactor

# Re-exported for the training script. The choice and its rationale live in
# deid/config.py, and it is overridable via DEID_BASE_MODEL.
DEFAULT_MODEL = BASE_MODEL


def label_list() -> list[str]:
    """O, then B-/I- for each category. Index 0 is always O."""
    labels = ["O"]
    for c in PhiCategory:
        labels.append(f"B-{c.value}")
        labels.append(f"I-{c.value}")
    return labels


def spans_to_bio(
    spans: tuple[PhiSpan, ...],
    offsets: list[tuple[int, int]],
    seq_ids: list[int | None],
    label_to_id: dict[str, int],
) -> list[int]:
    """Project character spans onto token labels.

    A token is labelled with a span if it overlaps it at all. The first
    overlapping token gets B-, the rest I-. Special tokens get -100 so the loss
    ignores them.
    """
    labels = [-100 if sid is None else 0 for sid in seq_ids]
    for span in spans:
        first = True
        for i, (tok_start, tok_end) in enumerate(offsets):
            if seq_ids[i] is None or tok_end <= tok_start:
                continue
            if tok_start < span.end and span.start < tok_end:
                prefix = "B" if first else "I"
                labels[i] = label_to_id[f"{prefix}-{span.category.value}"]
                first = False
    return labels


def bio_to_spans(
    tag_ids: list[int],
    offsets: list[tuple[int, int]],
    id_to_label: dict[int, str],
    text: str,
) -> list[PhiSpan]:
    """Decode BIO tags back into character spans.

    We treat a bare I- tag with no preceding B- as the start of a span rather
    than dropping it. Strict BIO decoding would discard PHI on a common model
    error, and discarding PHI is exactly the failure this project is about.
    """
    spans: list[PhiSpan] = []
    cur_cat: str | None = None
    cur_start = cur_end = 0

    def flush() -> None:
        nonlocal cur_cat
        if cur_cat is not None and cur_end > cur_start:
            spans.append(
                PhiSpan(start=cur_start, end=cur_end,
                        category=PhiCategory(cur_cat), text=text[cur_start:cur_end])
            )
        cur_cat = None

    for tag_id, (start, end) in zip(tag_ids, offsets):
        label = id_to_label.get(tag_id, "O")
        if end <= start:  # special token
            continue
        if label == "O":
            flush()
            continue
        prefix, _, cat = label.partition("-")
        if prefix == "B" or cur_cat != cat:
            flush()
            cur_cat, cur_start, cur_end = cat, start, end
        else:  # continuation
            cur_end = end
    flush()
    return spans


class TransformerRedactor(BaseRedactor):
    name = "transformer"
    transmits_offsite = False

    def __init__(self, model_dir: str | Path, device: str | None = None,
                 window: int = 512, stride: int = 128,
                 o_logit_penalty: float = 0.0) -> None:
        """
        o_logit_penalty
            Subtracted from the `O` logit before argmax. Zero reproduces plain
            argmax. Positive values make the model call a token PHI on weaker
            evidence, trading precision for recall.

            This is the inference-time half of the same asymmetry the training
            loss encodes with `--o-weight`: a missed name is a disclosure, an
            over-redacted word is an annoyance. Having the lever at inference
            time as well means the operating point can be moved without
            retraining — which is what you want when a compliance officer asks
            for a lower leak rate on Friday afternoon.
        """
        try:
            import torch
            from transformers import AutoModelForTokenClassification, AutoTokenizer
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "The transformer redactor needs: pip install -e '.[ml]'"
            ) from e

        self._torch = torch
        self.model_dir = str(model_dir)
        if device is None:
            device = (
                "cuda" if torch.cuda.is_available()
                else "mps" if torch.backends.mps.is_available()
                else "cpu"
            )
        self.device = device
        self.window = window
        self.stride = stride
        self.o_logit_penalty = o_logit_penalty

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
        self.model = AutoModelForTokenClassification.from_pretrained(self.model_dir)
        self.model.to(device).eval()

        cfg = self.model.config
        self.id_to_label = {int(k): v for k, v in cfg.id2label.items()}
        self.name = f"transformer:{Path(self.model_dir).name}"

    def find(self, text: str) -> tuple[PhiSpan, ...]:
        torch = self._torch
        enc = self.tokenizer(
            text,
            return_offsets_mapping=True,
            return_overflowing_tokens=True,
            max_length=self.window,
            stride=self.stride,
            truncation=True,
            padding=False,
        )

        all_spans: list[PhiSpan] = []
        for i in range(len(enc["input_ids"])):
            ids = torch.tensor([enc["input_ids"][i]], device=self.device)
            mask = torch.tensor([enc["attention_mask"][i]], device=self.device)
            with torch.inference_mode():
                logits = self.model(input_ids=ids, attention_mask=mask).logits
            if self.o_logit_penalty:
                # Index 0 is always O — see label_list().
                logits[..., 0] -= self.o_logit_penalty
            tag_ids = logits.argmax(-1)[0].tolist()

            offsets = enc["offset_mapping"][i]
            seq_ids = enc.sequence_ids(i)
            # Zero out special tokens so bio_to_spans skips them.
            cleaned = [
                (0, 0) if seq_ids[j] is None else tuple(offsets[j])
                for j in range(len(offsets))
            ]
            all_spans.extend(bio_to_spans(tag_ids, cleaned, self.id_to_label, text))

        # Overlapping windows produce duplicate spans; merge_spans in types.py
        # unions them at redaction time, but the eval harness scores raw spans,
        # so dedupe here.
        unique = {(s.start, s.end, s.category): s for s in all_spans}
        return tuple(sorted(unique.values()))
