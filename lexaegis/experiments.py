# SPDX-License-Identifier: Apache-2.0
# Modified for LexAegis from concepts in kubeedge/ianvs PRs #282/#283 at 8150672e.
"""Offline-only privacy experiment primitives; never imported by dispatch."""
from __future__ import annotations

import math
import random


def l2_clip(vector: list[float], max_norm: float) -> list[float]:
    if max_norm <= 0:
        raise ValueError("max_norm 必须大于 0")
    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
    scale = min(1.0, max_norm / max(norm, 1e-12))
    return [float(value) * scale for value in vector]


def gaussian_dp(vector: list[float], *, max_norm: float, noise_multiplier: float, seed: int) -> dict:
    if noise_multiplier <= 0:
        raise ValueError("noise_multiplier 必须大于 0")
    clipped = l2_clip(vector, max_norm)
    rng = random.Random(seed)
    sigma = max_norm * noise_multiplier
    return {"vector": [value + rng.gauss(0, sigma) for value in clipped], "clipped_norm": math.sqrt(sum(value * value for value in clipped)), "sigma": sigma}


def rdp_gaussian(*, noise_multiplier: float, steps: int, orders: list[float]) -> dict[float, float]:
    if noise_multiplier <= 0 or steps < 0 or any(order <= 1 for order in orders):
        raise ValueError("RDP 参数无效")
    return {float(order): steps * float(order) / (2 * noise_multiplier ** 2) for order in orders}


def rdp_to_epsilon(rdp: dict[float, float], delta: float) -> float:
    if not 0 < delta < 1 or not rdp:
        raise ValueError("delta 或 RDP 为空")
    return min(value + math.log(1 / delta) / (order - 1) for order, value in rdp.items())


def random_projection(vectors: list[list[float]], target_dim: int, seed: int) -> dict:
    if not vectors or not vectors[0] or target_dim <= 0:
        raise ValueError("投影输入无效")
    source_dim = len(vectors[0])
    if any(len(vector) != source_dim for vector in vectors):
        raise ValueError("向量维度不一致")
    rng = random.Random(seed)
    scale = 1 / math.sqrt(target_dim)
    matrix = [[rng.gauss(0, scale) for _ in range(target_dim)] for _ in range(source_dim)]
    output = [[sum(row[index] * matrix[index][column] for index in range(source_dim)) for column in range(target_dim)] for row in vectors]
    return {"vectors": output, "matrix": matrix, "seed": seed}


def saliency_mask(tokens: list[str], scores: list[float], fraction: float, mask_token: str = "[MASK]") -> list[str]:
    if len(tokens) != len(scores) or not 0 <= fraction <= 1:
        raise ValueError("显著性掩码参数无效")
    count = math.ceil(len(tokens) * fraction)
    selected = {index for index, _ in sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[:count]}
    return [mask_token if index in selected else token for index, token in enumerate(tokens)]


def mia_requires_real_outputs(target_outputs) -> dict:
    if not target_outputs:
        return {"outcome": "not_applicable", "detail": "未提供真实目标模型输出；禁止生成模拟 loss 或常量指标。"}
    return {"outcome": "not_run", "detail": "输入可用，但 MIA 需要由隔离 benchmark profile 显式运行。"}
