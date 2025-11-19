import csv
from dataclasses import dataclass
from typing import List

import numpy as np
import matplotlib.pyplot as plt

T_HORIZON = 30.0  # 30秒

@dataclass
class TickRow:
    ts: float
    price: float

@dataclass
class SweepRow:
    ts_start: float
    ts_end: float
    direction: int
    price_start: float
    price_end: float
    volume_total: float

def load_ticks(path: str) -> List[TickRow]:
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(TickRow(
                ts=float(r["ts"]),
                price=float(r["price"])
            ))
    # 按时间排序
    rows.sort(key=lambda x: x.ts)
    return rows

def load_sweeps(path: str) -> List[SweepRow]:
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(SweepRow(
                ts_start=float(r["ts_start"]),
                ts_end=float(r["ts_end"]),
                direction=int(r["direction"]),
                price_start=float(r["price_start"]),
                price_end=float(r["price_end"]),
                volume_total=float(r["volume_total"]),
            ))
    rows.sort(key=lambda x: x.ts_end)
    return rows

def compute_ret_mfe_mae(ticks: List[TickRow], sweeps: List[SweepRow]):
    # 为了快速遍历，用一个指针在 tick 序列上走
    ts_list = [t.ts for t in ticks]
    prices = [t.price for t in ticks]

    results = []  # (direction, ret_30, MFE_30, MAE_30, price0)

    n = len(ticks)
    idx = 0

    for ev in sweeps:
        t0 = ev.ts_end
        t1 = t0 + T_HORIZON

        # 移动 idx 到 >= t0 的位置
        while idx < n and ticks[idx].ts < t0:
            idx += 1
        if idx >= n:
            break

        # 选取 t0 时的 price0：用第一个 ts>=t0 的 tick
        price0 = ticks[idx].price

        # 向后遍历直到 t1
        j = idx
        max_price = price0
        min_price = price0

        while j < n and ticks[j].ts <= t1:
            p = ticks[j].price
            if p > max_price:
                max_price = p
            if p < min_price:
                min_price = p
            j += 1

        if j == idx:
            # 没有足够数据
            continue

        # T 终点的价格，用最后一个 <= t1 的 tick
        priceT = ticks[j-1].price

        ret_30 = (priceT - price0) / price0

        if ev.direction < 0:
            # down sweep：价格越跌越“顺势”
            mfe_30 = (min_price - price0) / price0   # 一般为负
            mae_30 = (max_price - price0) / price0   # 一般为正
        else:
            # up sweep：价格越涨越“顺势”
            mfe_30 = (max_price - price0) / price0
            mae_30 = (min_price - price0) / price0

        results.append((ev.direction, ret_30, mfe_30, mae_30, price0))

    return results

def main():
    ticks = load_ticks("ticks_eth.csv")
    sweeps = load_sweeps("sweeps_eth.csv")

    print(f"Loaded {len(ticks)} ticks, {len(sweeps)} sweep events")

    results = compute_ret_mfe_mae(ticks, sweeps)

    # 拆分 up / down
    down_ret = [r[1] for r in results if r[0] < 0]
    up_ret   = [r[1] for r in results if r[0] > 0]

    print(f"Down sweeps: {len(down_ret)}, Up sweeps: {len(up_ret)}")

    if down_ret:
        arr = np.array(down_ret)
        print("Down sweep 30s ret mean:", arr.mean())
        print("Down sweep 30s ret std :", arr.std())
        print("Down sweep 30s ret median:", np.median(arr))

        plt.figure()
        plt.hist(arr, bins=50, alpha=0.7)
        plt.axvline(0, linestyle="--")
        plt.title("Down sweep 30s return distribution")
        plt.xlabel("ret_30")
        plt.ylabel("count")
        plt.grid(True)
        plt.tight_layout()
        plt.show()
    else:
        print("No down sweeps found")

if __name__ == "__main__":
    main()
