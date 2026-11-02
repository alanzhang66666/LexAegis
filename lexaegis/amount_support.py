"""Deterministic monetary-token consistency, not semantic/legal verification.

Compare only the cited facts' disclosed outputs. Do not search unrelated facts,
use local originals to excuse cloud invention, infer totals, or convert currency.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext
import re
import unicodedata

from .util import digest

VERSION = "amount-support-v1"
NUMBER = r"[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
MONEY = re.compile(
    r"(?<![0-9.,A-Za-z])(?P<prefix>人民币|RMB|CNY|USD|HKD|EUR|JPY|VND|[$¥€])?\s*"
    + r"(?P<number>" + NUMBER + r")\s*(?P<scale>亿|万|千)?\s*"
    + r"(?P<unit>人民币|美元|港元|欧元|日元|越南盾|元|圆|CNY|USD|HKD|EUR|JPY|VND)?",
    re.IGNORECASE,
)
CURRENCIES = {"人民币":"CNY", "rmb":"CNY", "cny":"CNY", "美元":"USD", "usd":"USD",
              "港元":"HKD", "hkd":"HKD", "欧元":"EUR", "eur":"EUR", "€":"EUR",
              "日元":"JPY", "jpy":"JPY", "越南盾":"VND", "vnd":"VND",
              "元":"元", "圆":"元", "¥":"yen_sign", "$":"dollar_sign"}
SCALES = {None: 1, "千": 1000, "万": 10000, "亿": 100000000}


@dataclass(frozen=True)
class Amount:
    value: Decimal
    unit: str
    start: int
    end: int

    def public(self):
        value = format(self.value, "f")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        return {"value": value or "0", "unit": self.unit, "start": self.start, "end": self.end}


def amounts(text):
    # Preserve original offsets even when NFKC expands a character.
    chars, positions = [], []
    for index, char in enumerate(text):
        normalized = unicodedata.normalize("NFKC", char)
        chars.extend(normalized); positions.extend([index] * len(normalized))
    normalized = "".join(chars)
    result = []
    for match in MONEY.finditer(normalized):
        prefix, unit = match.group("prefix", "unit")
        if not prefix and not unit:
            continue
        # Do not turn an unhandled grouping/exponent into a supported suffix.
        if (re.search(r"[0-9][\s,._]*$", normalized[:match.start()])
                or re.match(r"(?:[.,eE][+-]?[0-9]|[0-9])", normalized[match.end():])):
            continue
        before = CURRENCIES.get((prefix or "").lower())
        after = CURRENCIES.get((unit or "").lower())
        # Bare 元 does not establish CNY. A written explicit currency is retained.
        if before and after and before != after and not (before == "CNY" and after == "元"):
            continue
        currency = before or after
        raw = match.group("number").replace(",", "")
        with localcontext() as context:
            context.prec = max(28, len(raw) + 12)
            value = Decimal(raw) * SCALES[match.group("scale")]
        result.append(Amount(value, currency, positions[match.start()], positions[match.end()-1]+1))
    return result


def assess(claim_text, disclosed_sources):
    """Return a server-computed, hash-bound numeric report; never entailment."""
    cited = [(source_id, output) for source_id, output in disclosed_sources if output]
    supported = {}
    for source_id, output in cited:
        for amount in amounts(output):
            supported.setdefault((amount.value, amount.unit), set()).add(source_id)
    returned = amounts(claim_text)
    checks = [{**item.public(), "matched_source_ids": sorted(supported.get((item.value, item.unit), set()))}
              for item in returned]
    missing = [item for item in checks if not item["matched_source_ids"]]
    return {"validator_version": VERSION, "disclosed_support_hash": digest(cited),
            "status": "unsupported_amount" if missing else "numeric_consistency_only" if checks else "no_amount_tokens_checked",
            "semantic_entailment_verified": False, "amounts": checks, "unsupported_amounts": missing}
