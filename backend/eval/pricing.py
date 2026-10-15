"""DeepSeek 价格（美元 / 百万 tokens，高峰时段），用于估算成本。

来源：https://api-docs.deepseek.com/quick_start/pricing（2026-10-15 查阅）。
低峰时段价格为高峰的一半，这里统一按高峰价格保守估算。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    cache_hit: float
    cache_miss: float
    output: float


PRICES: dict[str, Price] = {
    "deepseek-flash": Price(cache_hit=0.006, cache_miss=0.3, output=1.2),
    "deepseek-v4-pro": Price(cache_hit=0.044, cache_miss=1.32, output=3.96),
}


def estimate_cost(
    model: str, prompt_tokens: int, cache_hit_tokens: int, completion_tokens: int
) -> float:
    price = PRICES.get(model)
    if price is None:
        return 0.0
    miss = prompt_tokens - cache_hit_tokens
    return (
        cache_hit_tokens * price.cache_hit
        + miss * price.cache_miss
        + completion_tokens * price.output
    ) / 1_000_000
