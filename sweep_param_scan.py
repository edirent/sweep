import csv
from dataclasses import dataclass
from typing import List, Tuple
import numpy as np

# === 前瞻窗口 ===
T_HORIZON = 30.0  # 30 秒

# === 参数搜索网格 ===
WINDOW_LIST = [0.3, 0.6, 1.0]           # sweep 检测窗口长度 (秒)
PRICE_BP_LIST = [3, 5, 8]              # 价格单边变动阈值 (bp)
VOL_MIN_LIST = [2.0, 5.0, 10.0]        # 最小成交量 (ETH)


@dataclass
class TickRow:
    ts: float
    price: float
    vol: float
    side: int  # +1=Buy, -1=Sell


@dataclass
class PySweep:
    ts_start: float
    ts_end: float
    direction: int     # +1 up, -1 down
    price_start: float
    price_end: float
    volume_total: float


def load_ticks(path: str = "ticks_eth.csv") -> List[TickRow]:
    rows: List[TickRow] = []
    with open(path, "r") as f:
        r = csv.DictReader(f)
        for row in r:
            ts = float(row["ts"])
            price = float(row["price"])
            vol = float(row["volume"])
            side = 1 if row["side"] == "B" else -1
            rows.append(TickRow(ts, price, vol, side))
    rows.sort(key=lambda x: x.ts)
    return rows


def detect_sweeps_py(
    ticks: List[TickRow],
    window_sec: float,
    price_bp_thresh: float,
    vol_min: float,
) -> List[PySweep]:
    sweeps: List[PySweep] = []
    n = len(ticks)
    i = 0
    while i < n:
        j = i
        base_p = ticks[i].price
        base_t = ticks[i].ts
        up_max = base_p
        dn_min = base_p
        up_vol = 0.0
        dn_vol = 0.0

        while j < n and ticks[j].ts - base_t <= window_sec:
            p = ticks[j].price
            v = ticks[j].vol

            if p > up_max:
                up_max = p
            if p < dn_min:
                dn_min = p

            # 简单按价格方向划归成交量
            if p >= base_p:
                up_vol += v
            if p <= base_p:
                dn_vol += v

            j += 1

        up_bp = (up_max - base_p) / base_p * 10000.0
        dn_bp = (base_p - dn_min) / base_p * 10000.0

        if up_bp >= price_bp_thresh and up_vol >= vol_min:
            sweeps.append(
                PySweep(
                    ts_start=base_t,
                    ts_end=ticks[j - 1].ts,
                    direction=+1,
                    price_start=base_p,
                    price_end=up_max,
                    volume_total=up_vol,
                )
            )
        elif dn_bp >= price_bp_thresh and dn_vol >= vol_min:
            sweeps.append(
                PySweep(
                    ts_start=base_t,
                    ts_end=ticks[j - 1].ts,
                    direction=-1,
                    price_start=base_p,
                    price_end=dn_min,
                    volume_total=dn_vol,
                )
            )

        i += 1

    return sweeps


def compute_ret_stats(
    ticks: List[TickRow],
    sweeps: List[PySweep],
    horizon: float = T_HORIZON,
) -> Tuple[np.ndarray, np.ndarray]:
    ts = [t.ts for t in ticks]
    px = [t.price for t in ticks]
    n = len(ticks)

    down_rets = []
    up_rets = []

    for ev in sweeps:
        t0 = ev.ts_end
        t1 = t0 + horizon

        i0 = None
        for i in range(n):
            if ts[i] >= t0:
                i0 = i
                break
        if i0 is None:
            continue

        p0 = px[i0]
        max_p = p0
        min_p = p0

        j = i0
        while j < n and ts[j] <= t1:
            p = px[j]
            if p > max_p:
                max_p = p
            if p < min_p:
                min_p = p
            j += 1
        if j == i0:
            continue

        pT = px[j - 1]
        ret = (pT - p0) / p0

        if ev.direction < 0:
            down_rets.append(ret)
        else:
            up_rets.append(ret)

    return np.array(down_rets), np.array(up_rets)


def summarize(label: str, arr: np.ndarray) -> str:
    if arr.size == 0:
        return f"{label}: count=0"
    return (
        f"{label}: count={arr.size}, "
        f"mean={arr.mean():.6f}, std={arr.std():.6f}, "
        f"med={np.median(arr):.6f}"
    )


def main():
    ticks = load_ticks("ticks_eth.csv")
    print(f"[INFO] loaded {len(ticks)} ticks from ticks_eth.csv")

    for w in WINDOW_LIST:
        for bp in PRICE_BP_LIST:
            for vol_min in VOL_MIN_LIST:
                sweeps = detect_sweeps_py(ticks, w, bp, vol_min)
                down_rets, up_rets = compute_ret_stats(ticks, sweeps)

                print("=" * 80)
                print(
                    f"window={w:.2f}s, bp={bp}, vol_min={vol_min} "
                    f"-> sweeps={len(sweeps)}"
                )
                print("  " + summarize("Down", down_rets))
                print("  " + summarize("Up  ", up_rets))


if __name__ == "__main__":
    main()
