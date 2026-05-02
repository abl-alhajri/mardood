"""
Mardood — Hugging Face sentiment models

ProsusAI/finbert  — financial sentiment (positive / negative / neutral)
ElKulako/cryptobert — crypto-native sentiment (Bullish / Bearish / Neutral)

Both run via the public HF inference API. Calls are deduplicated per
(model, text) for 25 minutes so we don't hit the free tier ceiling on
every 30-minute scan cycle.
"""
import os
import time
import requests
from config import HUGGINGFACE_API_KEY

HF_BASE = "https://api-inference.huggingface.co/models"
FINBERT_MODEL = "ProsusAI/finbert"
CRYPTOBERT_MODEL = "ElKulako/cryptobert"

_FINBERT_POS = {"positive"}
_FINBERT_NEG = {"negative"}
_CRYPTOBERT_POS = {"bullish"}
_CRYPTOBERT_NEG = {"bearish"}

_CACHE_TTL = 25 * 60  # seconds — just under the 30-min scan interval
_cache: dict[tuple[str, str], tuple[float, list[dict] | None]] = {}


def _hf_classify(model_id: str, text: str, timeout: int = 20) -> list[dict] | None:
    """Run text through an HF text-classification model. Returns list of {label, score} or None on error."""
    if not HUGGINGFACE_API_KEY:
        return None
    text = text.strip()
    if not text:
        return None

    key = (model_id, text)
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    try:
        r = requests.post(
            f"{HF_BASE}/{model_id}",
            headers={"Authorization": f"Bearer {HUGGINGFACE_API_KEY}"},
            json={"inputs": text[:512], "options": {"wait_for_model": True}},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        _cache[key] = (now, None)
        return None

    # API returns either [[{label, score}, ...]] for a single input
    # or [{label, score}, ...] depending on model + version. Normalize.
    scores = None
    if isinstance(data, list) and data:
        if isinstance(data[0], list):
            scores = data[0]
        elif isinstance(data[0], dict):
            scores = data

    _cache[key] = (now, scores)
    return scores


def _aggregate(per_text_scores: list[list[dict]], pos_labels: set[str], neg_labels: set[str]) -> dict | None:
    """Aggregate per-text scores into mean bullish/bearish/neutral."""
    pos = neg = neu = 0.0
    n = 0
    for scores in per_text_scores:
        if not scores:
            continue
        n += 1
        for s in scores:
            label = str(s.get("label", "")).strip().lower()
            score = float(s.get("score", 0))
            if label in pos_labels:
                pos += score
            elif label in neg_labels:
                neg += score
            else:
                neu += score
    if n == 0:
        return None
    return {
        "bullish": pos / n,
        "bearish": neg / n,
        "neutral": neu / n,
        "n": n,
        "net": (pos - neg) / n,  # in [-1, 1] — positive means bullish lean
    }


def analyze_finbert(headlines: list[str]) -> dict | None:
    if not headlines:
        return None
    per = [_hf_classify(FINBERT_MODEL, h) for h in headlines]
    return _aggregate(per, _FINBERT_POS, _FINBERT_NEG)


def analyze_cryptobert(headlines: list[str]) -> dict | None:
    if not headlines:
        return None
    per = [_hf_classify(CRYPTOBERT_MODEL, h) for h in headlines]
    return _aggregate(per, _CRYPTOBERT_POS, _CRYPTOBERT_NEG)


def format_sentiment(label: str, result: dict | None) -> str:
    if not result:
        return ""
    net = result["net"]
    lean = "bullish" if net > 0.15 else "bearish" if net < -0.15 else "neutral"
    return (
        f"{label} sentiment (n={result['n']}, lean: {lean}): "
        f"{result['bullish']*100:.0f}% bullish, "
        f"{result['bearish']*100:.0f}% bearish, "
        f"{result['neutral']*100:.0f}% neutral, "
        f"net={net:+.2f}"
    )
