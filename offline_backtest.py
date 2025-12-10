"""
Simple offline backtest to replay ticks through SweepModel + MeanReversionStrategy.
Default ticks file: ticks_eth.csv (ts, price, volume, side[B/S]).
"""

import argparse
import csv

from sweep_core import (
    SweepModel,
    Side,
    Tick,
    SweepSignal,
    MeanReversionStrategy,
    StrategyActionType,
)


# 默认参数与 live_bybit_strategy 对齐（可通过命令行覆盖）
SWEEP_SHORT_WIN_SEC = 0.30
SWEEP_LONG_WIN_SEC = 10.0
SWEEP_THRESHOLD_RATIO = 1.0

DELAY_MS = 5.0
HOLD_SEC = 15.0
TP_BP = 1.0
SL_BP = 8.0


def parse_args():
    ap = argparse.ArgumentParser(description="Offline backtest for sweep + strategy.")
    ap.add_argument("--ticks", default="ticks_eth.csv", help="CSV with columns ts,price,volume,side[B/S]")
    ap.add_argument("--limit", type=int, default=0, help="Max rows to replay (0 means all).")
    return ap.parse_args()


def load_ticks(path, limit=0):
    count = 0
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for r in reader:
            ts = float(r["ts"])
            price = float(r["price"])
            vol = float(r.get("volume", r.get("vol", 0)))
            side_raw = r["side"]
            side = Side.Buy if side_raw in ("B", "Buy") else Side.Sell
            yield ts, price, vol, side
            count += 1
            if limit and count >= limit:
                break


def main():
    args = parse_args()

    sweep_model = SweepModel(
        short_window_sec=SWEEP_SHORT_WIN_SEC,
        long_window_sec=SWEEP_LONG_WIN_SEC,
        threshold_ratio=SWEEP_THRESHOLD_RATIO,
    )
    strategy = MeanReversionStrategy(
        delay_ms=DELAY_MS,
        hold_sec=HOLD_SEC,
        tp_bp=TP_BP,
        sl_bp=SL_BP,
    )

    current_dir = 0
    entry_price = None
    wins = 0
    losses = 0
    cum_pnl = 0.0

    sweep_cnt = 0
    open_cnt = 0
    close_cnt = 0

    for ts, price, vol, side in load_ticks(args.ticks, args.limit):
        # Sweep detection
        tick = Tick()
        tick.timestamp = ts
        tick.price = price
        tick.volume = vol
        tick.side = side

        sig = sweep_model.process_tick(tick)
        if sig != SweepSignal.NoSignal:
            sweep_cnt += 1
            ev = sweep_model.get_last_event()
            act = strategy.on_sweep(ev)
            if act.type == StrategyActionType.OpenLong:
                current_dir = 1
                entry_price = act.price
                open_cnt += 1
            elif act.type == StrategyActionType.OpenShort:
                current_dir = -1
                entry_price = act.price
                open_cnt += 1
            elif act.type == StrategyActionType.Close and current_dir != 0 and entry_price is not None:
                pnl = (act.price - entry_price) * current_dir
                cum_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                current_dir = 0
                entry_price = None
                close_cnt += 1

        # Position management
        act_tick = strategy.on_tick(ts, price)
        if act_tick.type == StrategyActionType.Close and current_dir != 0 and entry_price is not None:
            pnl = (act_tick.price - entry_price) * current_dir
            cum_pnl += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
            current_dir = 0
            entry_price = None
            close_cnt += 1

    total_trades = wins + losses
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0.0

    print(f"Replayed ticks: {args.limit or 'all'} from {args.ticks}")
    print(f"Sweeps detected: {sweep_cnt}")
    print(f"Opens: {open_cnt}, Closes: {close_cnt}")
    print(f"Wins: {wins}, Losses: {losses}, WinRate: {win_rate:4.1f}%")
    print(f"Cum PnL (mark): {cum_pnl:.6f}")


if __name__ == "__main__":
    main()
