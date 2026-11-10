"""Parse free-text prices from listings ("₹300-2500", "₹700/₹1500", "Rs 500") into numbers."""
import re

_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)")


def parse_price_range(text: str) -> tuple[float, float] | None:
    """Return (low, high) in INR, or None if no number is present.

    A single number gives (n, n). Several numbers give (min, max), e.g. '₹700/₹1500' ->
    (700, 1500). Numbers that look like years or phone digits (> 200000) are ignored.
    """
    if not text:
        return None
    nums = []
    for raw in _NUM.findall(text):
        value = float(raw.replace(",", ""))
        if 0 < value <= 200_000:
            nums.append(value)
    if not nums:
        return None
    return min(nums), max(nums)
