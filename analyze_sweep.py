import csv
from dataclasses import dataclass
from typing import List
import numpy as np
import matplotlib.pyplot as plt

from sweep_core import SweepModel, Tick, Side, SweepSignal

# ========= 你要调的 SweepModel 参数，全写在这里 =========
SHORT_WIN = 0.15   # 短窗口秒数，例如 0.15s
LONG_WIN  = 3.0    # 长窗口秒数，例如 3s
THRESH    = 0.8    # 阈值，越小事件越多（先用 0.8，太少就再降）
T_HORIZON = 30.0   # 前瞻 30 秒
# =======================================================


@dataclass
class TickRow:
    ts: float
    price: float


@dataclass
class SweepRow:
    ts_start: float
    ts_end: float
    direction: int   # 1=Up, -1=Down
    price_start: float
    price_end: float
    volume_total: float


def load_ticks(path: str = "ticks_eth.csv") -> List[TickRow]:
    rows: List[TickRow] = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(
                TickRow(
                    ts=float(r["ts"]),
                    price=float(r["price"]),
                )
            )
    rows.sort(key=lambda x: x.ts)
    return rows


def generate_sweeps_from_ticks(ticks_path: str) -> List[SweepRow]:
    """
    用 SweepModel + 当前参数，从 ticks_eth.csv 生成 sweep 事件（完全离线）。
    """
    model = SweepModel(
        short_window_sec=SHORT_WIN,
        long_window_sec=LONG_WIN,
        threshold_ratio=THRESH,
    )

    sweeps: List[SweepRow] = []

    with open(ticks_path, "r") as f:
        reader = csv.DictReader(f)
        for r in reader:
            tick = Tick()
            tick.timestamp = float(r["ts"])
            tick.price = float(r["price"])
            tick.volume = float(r["volume"])
            tick.side = Side.Buy if r["side"] == "B" else Side.Sell

            sig = model.process_tick(tick)
            if sig != SweepSignal.NoSignal:
                ev = model.get_last_event()
                if ev.direction == 0:
                    continue
                sweeps.append(
                    SweepRow(
                        ts_start=ev.ts_start,
                        ts_end=ev.ts_end,
                        direction=ev.direction,
                        price_start=ev.price_start,
                        price_end=ev.price_end,
                        volume_total=ev.volume_total,
                    )
                )

    print(f"[INFO] Generated {len(sweeps)} sweep events from ticks with "
          f"SHORT_WIN={SHORT_WIN}, LONG_WIN={LONG_WIN}, THRESH={THRESH}")
    return sweeps


def compute_ret_mfe_mae(ticks: List[TickRow],
                        sweeps: List[SweepRow],
                        horizon: float = T_HORIZON):
    ts_list = [t.ts for t in ticks]
    prices = [t.price for t in ticks]
    n = len(ticks)

    results = []  # (direction, ret_h, mfe_h, mae_h, volume_total)

    for ev in sweeps:
        t0 = ev.ts_end
        t1 = t0 + horizon

        # 找到第一个 ts >= t0 的 index（可以之后改成二分）
        i0 = None
        for i in range(n):
            if ts_list[i] >= t0:
                i0 = i
                break
        if i0 is None:
            continue

        price0 = prices[i0]
        max_p = price0
        min_p = price0

        j = i0
        while j < n and ts_list[j] <= t1:
            p = prices[j]
            if p > max_p:
                max_p = p
            if p < min_p:
                min_p = p
            j += 1
        if j == i0:
            continue

        priceT = prices[j - 1]
        ret_h = (priceT - price0) / price0

        if ev.direction < 0:
            # down sweep：价格向下为顺势
            mfe_h = (min_p - price0) / price0
            mae_h = (max_p - price0) / price0
        else:
            # up sweep：价格向上为顺势
            mfe_h = (max_p - price0) / price0
            mae_h = (min_p - price0) / price0

        results.append((ev.direction, ret_h, mfe_h, mae_h, ev.volume_total))

    return results


def summarize_and_plot(label: str, rets: np.ndarray):
    print(f"{label}: count={len(rets)}")
    print(f"{label}: mean={rets.mean():.6f}")
    print(f"{label}: std ={rets.std():.6f}")
    print(f"{label}: median={np.median(rets):.6f}")
    print(f"{label}: 5%={np.percentile(rets, 5):.6f}, "
          f"95%={np.percentile(rets, 95):.6f}")
    print()

    plt.figure()
    plt.hist(rets, bins=40, alpha=0.7)
    plt.axvline(0.0, linestyle="--")
    plt.title(f"{label} {int(T_HORIZON)}s return distribution")
    plt.xlabel("ret")
    plt.ylabel("count")
    plt.grid(True)
    plt.tight_layout()


def main():
    ticks = load_ticks("ticks_eth.csv")
    print(f"[INFO] Loaded {len(ticks)} ticks")

    sweeps = generate_sweeps_from_ticks("ticks_eth.csv")

    results = compute_ret_mfe_mae(ticks, sweeps, horizon=T_HORIZON)

    down_ret = [r[1] for r in results if r[0] < 0]
    up_ret   = [r[1] for r in results if r[0] > 0]

    print(f"Down sweeps: {len(down_ret)}, Up sweeps: {len(up_ret)}\n")

    if down_ret:
        summarize_and_plot("Down sweep", np.array(down_ret))
    else:
        print("No down sweeps found\n")

    if up_ret:
        summarize_and_plot("Up sweep", np.array(up_ret))
    else:
        print("No up sweeps found\n")

    if down_ret or up_ret:
        plt.show()


if __name__ == "__main__":
    main()
