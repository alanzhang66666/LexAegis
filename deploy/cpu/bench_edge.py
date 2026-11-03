"""实测 CPU 上边侧模型抽取一块材料要多久（全部使用合成文本）。

用法（部署完成后，在仓库根目录）：
    docker compose exec -T api python - < deploy/cpu/bench_edge.py
    docker compose exec -T -e SIZES=1000,3000,6000 api python - < deploy/cpu/bench_edge.py

做法与 worker 一致：每块材料调用一次 EdgeClient.extract(second_pass=True)，超时取
LEX_EDGE_REQUEST_TIMEOUT（默认 120 秒）。超时、JSON 不合格都记为失败。
结果怎么用：
  · 某档“失败”：这个大小的块在当前配置下会抽取失败，调小 LEX_EDGE_EXTRACT_CHUNK_CHARS 或调大超时
  · 全部通过：整份材料耗时 ≈ 块数 × 单块耗时，决定能不能接受
"""
import math
import os
import time

from lexaegis.edge_eval import score_extract
from lexaegis.providers import EdgeClient, edge_request_timeout

SIZES = [int(x) for x in os.getenv("SIZES", "1000,3000").split(",") if x.strip()]
UNITS = [
    "张某于{y}年{m}月{d}日入职某科技公司，担任测试工程师，约定月工资人民币{a}元。",
    "公司自{y}年{m}月起未足额支付工资，累计拖欠{a}元，张某多次向人事部门书面催告。",
    "{y}年{m}月{d}日，公司通知张某调岗至外地分部，张某表示不同意并提出异议。",
    "张某每周工作六天，{y}年{m}月加班共计{d}小时，公司未支付加班费。",
]


def make_block(index, length):
    text = ""
    step = 0
    while len(text) < length:
        text += UNITS[step % len(UNITS)].format(y=2020 + (index + step) % 5, m=1 + (index * 3 + step) % 12,
                                                 d=1 + (index * 7 + step) % 28, a=3000 + 100 * ((index + step) % 40))
        step += 1
    return {"id": f"bench:b{index}", "text": text[:length]}


client = EdgeClient(os.environ["LEX_EDGE_URL"], os.getenv("LEX_EDGE_MODEL", "edge-small"))
print(f"模型 {client.model}  地址 {client.url}  超时 {edge_request_timeout()} 秒  "
      f"分块 {os.getenv('LEX_EDGE_EXTRACT_CHUNK_CHARS', '14000(默认)')} 字 / {os.getenv('LEX_EDGE_EXTRACT_CHUNK_BLOCKS', '8(默认)')} 段")
print(f"{'块大小(字)':>10} {'耗时(秒)':>9} {'事实':>5} {'引用':>6} {'数字':>6}  结果")
for size in SIZES:
    per_block = min(size, 750)
    blocks = [make_block(i, per_block if (i + 1) * per_block <= size else size - i * per_block)
              for i in range(math.ceil(size / per_block))]
    started = time.time()
    try:
        facts = client.extract(blocks, second_pass=True)
        seconds = round(time.time() - started, 1)
        score = score_extract(blocks, facts)
        print(f"{size:>10} {seconds:>9} {len(facts):>5} {str(score['quote_is_substring']):>6} "
              f"{str(score['numbers_from_source']):>6}  通过")
    except Exception as error:  # 超时、连接失败、JSON 不合格
        print(f"{size:>10} {round(time.time() - started, 1):>9} {'-':>5} {'-':>6} {'-':>6}  失败：{type(error).__name__} {str(error)[:80]}")
