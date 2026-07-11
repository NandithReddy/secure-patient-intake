"""Model choices, in one place, overridable by environment.

The base model is a *choice*, not a constant. It was selected empirically —
see the note below — and the next person to run this on different hardware may
need a different one. Hard-coding it into the training script would bury that.

    DEID_BASE_MODEL=roberta-base python -m deid.train --out models/x
"""

from __future__ import annotations

import os

# Why roberta-base and not deberta-v3-base:
#
# DeBERTa-v3 produces NaN losses under Apple's MPS backend (torch 2.13 /
# transformers 5.13). The weights corrupt during the first epoch and every
# token subsequently argmaxes to the O class, which presents as a token recall
# of exactly 0.000 — a symptom easy to misread as an undertrained model rather
# than a numerically broken one. Observed on a 60-note / 2-epoch probe.
#
# Whether DeBERTa-v3 trains cleanly on CPU is UNVERIFIED: the probe was still
# running after ~15 minutes (versus 24 seconds for RoBERTa on MPS) and was
# abandoned. So the CPU path is untested, not vindicated.
#
# RoBERTa trains cleanly on MPS and is fast enough for the sweeps this project
# depends on, so it is the portable default. Override on a CUDA box, where
# DeBERTa is generally a point or two better on token classification.
BASE_MODEL = os.environ.get("DEID_BASE_MODEL", "roberta-base")

# Inference-time bias against the O class. See TransformerRedactor.
#
# Missing a name is a disclosure; over-redacting a word is an annoyance. The
# operating point should sit on the recall side of the argmax, and this is the
# lever that puts it there without retraining.
O_LOGIT_PENALTY = float(os.environ.get("DEID_O_LOGIT_PENALTY", "0.0"))

# Training-time counterpart: down-weight the O class in the loss.
O_CLASS_WEIGHT = float(os.environ.get("DEID_O_CLASS_WEIGHT", "0.3"))
