"""
Quick order book structure probe for Bybit.

- Subscribes to trades + L2 orderbook (50) + tickers.
- Computes AggBuy/Sell over 1s/3s/10s windows and highlights 3–5s directional runs.
- Measures depth within 0.1%/0.3%/0.5% of mid to spot the weak side.

This is a research tool only: it prints observations to stdout and does not trade.
"""

import argparse
import json
import time
import traceback
from collections import deque
from typing import Deque, Dict, List, Tuple

import websocket  # pip install websocket-client


def now_ts() -> float:
    return time.time()


class AggFlowTracker:
    """Tracks aggressive buy/sell flow over sliding windows (in seconds)."""

    def __init__(self, windows: List[float]):
        self.windows = sorted(windows)
        self.trades: Deque[Tuple[float, int, float]] = deque()  # (ts, dir(+1/-1), vol)

    def add_trade(self, ts: float, side: str, vol: float):
        direction = 1 if side.lower().startswith("b") else -1
        self.trades.append((ts, direction, vol))
        self._prune(ts)

    def _prune(self, ts_now: float):
        cutoff = ts_now - self.windows[-1]
        while self.trades and self.trades[0][0] < cutoff:
            self.trades.popleft()

    def summary(self, ts_now: float):
        """Return per-window stats: buy, sell, total, buy_share, net."""
        self._prune(ts_now)
        sums: Dict[float, Dict[str, float]] = {
            w: {"buy": 0.0, "sell": 0.0} for w in self.windows
        }
        for ts, direction, vol in self.trades:
            age = ts_now - ts
            for w in self.windows:
                if age <= w:
                    if direction > 0:
                        sums[w]["buy"] += vol
                    else:
                        sums[w]["sell"] += vol

        out = {}
        for w, v in sums.items():
            total = v["buy"] + v["sell"]
            buy_share = v["buy"] / total if total > 0 else 0.0
            out[w] = {
                "buy": v["buy"],
                "sell": v["sell"],
                "total": total,
                "buy_share": buy_share,
                "net": v["buy"] - v["sell"],
            }
        return out


class OrderBookL2:
    """Maintains a light L2 book (50 levels) and computes depth bands."""

    def __init__(self):
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_ts = 0.0

    def apply_snapshot(self, data: dict):
        book = data
        self.bids = {
            float(p): float(s) for p, s in book.get("b", []) if float(s) > 0
        }
        self.asks = {
            float(p): float(s) for p, s in book.get("a", []) if float(s) > 0
        }
        self.last_ts = now_ts()

    def apply_delta(self, data: dict):
        for p, s in data.get("b", []):
            price, size = float(p), float(s)
            if size <= 0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = size
        for p, s in data.get("a", []):
            price, size = float(p), float(s)
            if size <= 0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = size
        self.last_ts = now_ts()

    def best_bid(self):
        return max(self.bids) if self.bids else None

    def best_ask(self):
        return min(self.asks) if self.asks else None

    def mid(self):
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return 0.5 * (bid + ask)

    def liquidity_within(self, pct: float) -> Tuple[float, float]:
        """
        Depth within +/- pct of mid.
        pct=0.001 -> 0.1%
        """
        mid = self.mid()
        if mid is None:
            return 0.0, 0.0
        lower = mid * (1 - pct)
        upper = mid * (1 + pct)
        bid_depth = sum(sz for px, sz in self.bids.items() if px >= lower)
        ask_depth = sum(sz for px, sz in self.asks.items() if px <= upper)
        return bid_depth, ask_depth


class ProbeReporter:
    """Builds human-friendly pulses for AggFlow and OB weakness."""

    def __init__(
        self,
        agg_tracker: AggFlowTracker,
        ob: OrderBookL2,
        print_interval: float,
        log_file: str | None = None,
    ):
        self.agg_tracker = agg_tracker
        self.ob = ob
        self.print_interval = print_interval
        self.last_emit = 0.0
        self.bias_hist: Deque[dict] = deque(maxlen=5)
        self.last_price = None  # fallback mid if book not ready
        self.log_fp = open(log_file, "a", buffering=1) if log_file else None

    def _log(self, line: str):
        if self.log_fp:
            try:
                self.log_fp.write(line + "\n")
            except Exception:
                pass

    def _detect_run(self, ts_now: float, agg_stats: dict):
        one_sec = agg_stats.get(1.0) or agg_stats.get(1)  # tolerate float/int keys
        if not one_sec:
            return None
        net = one_sec["net"]
        total = one_sec["total"]
        if total <= 0:
            return None
        direction = 1 if net > 0 else -1 if net < 0 else 0
        if direction == 0:
            return None

        self.bias_hist.append(
            {
                "ts": ts_now,
                "dir": direction,
                "net": net,
                "share": one_sec["buy_share"],
            }
        )

        if len(self.bias_hist) < 3:
            return None
        recent = list(self.bias_hist)[-3:]
        dirs = [r["dir"] for r in recent]
        if not all(d == dirs[0] and d != 0 for d in dirs):
            return None
        mags = [abs(r["net"]) for r in recent]
        last_share = recent[-1]["share"]
        # Strengthen if magnitude is non-decreasing and buying/selling share is decisive.
        strong_share = (
            last_share >= 0.7 if dirs[0] > 0 else last_share <= 0.3
        )
        if mags[0] <= mags[1] <= mags[2] and strong_share:
            return {
                "dir": "BUY" if dirs[0] > 0 else "SELL",
                "net": recent[-1]["net"],
                "share": recent[-1]["share"],
            }
        return None

    def maybe_emit(self):
        ts_now = now_ts()
        if ts_now - self.last_emit < self.print_interval:
            return

        mid = self.ob.mid()
        if mid is None:
            # Use last trade as a weak placeholder to keep time moving.
            if self.last_price is None:
                return
            mid = self.last_price

        agg_stats = self.agg_tracker.summary(ts_now)
        run = self._detect_run(ts_now, agg_stats)

        bands = [0.001, 0.003, 0.005]  # 0.1%, 0.3%, 0.5%
        liq_stats = []
        weak_msgs = []
        for pct in bands:
            bid_depth, ask_depth = self.ob.liquidity_within(pct)
            liq_stats.append((pct, bid_depth, ask_depth))
            weak_side = None
            ratio = None
            if bid_depth > 0 and ask_depth > 0:
                if bid_depth < 0.4 * ask_depth:
                    weak_side = "bid"
                    ratio = bid_depth / ask_depth
                elif ask_depth < 0.4 * bid_depth:
                    weak_side = "ask"
                    ratio = ask_depth / bid_depth
            if weak_side:
                weak_msgs.append(
                    f"{int(pct*1000)/10:.1f}% weak {weak_side} ({ratio:.2f}x)"
                )

        bid, ask = self.ob.best_bid(), self.ob.best_ask()
        one = agg_stats.get(1.0) or agg_stats.get(1)
        three = agg_stats.get(3.0) or agg_stats.get(3)
        ten = agg_stats.get(10.0) or agg_stats.get(10)

        line_parts = [
            f"[{time.strftime('%H:%M:%S', time.localtime(ts_now))}]",
            f"mid={mid:.2f}",
            f"bb={bid:.2f}" if bid else "bb=?",
            f"ba={ask:.2f}" if ask else "ba=?",
        ]

        def fmt_window(label, stats):
            if not stats or stats["total"] <= 0:
                return f"{label}:0/0"
            buy = stats["buy"]
            sell = stats["sell"]
            share = stats["buy_share"] * 100
            return f"{label}:{buy:.1f}/{sell:.1f} ({share:4.1f}% buy)"

        line_parts.append(fmt_window("1s", one))
        line_parts.append(fmt_window("3s", three))
        line_parts.append(fmt_window("10s", ten))

        depth_strs = []
        for pct, b, a in liq_stats:
            depth_strs.append(
                f"Liq{int(pct*1000)/10:.1f}% b={b:.1f} a={a:.1f}"
            )
        if depth_strs:
            line_parts.append(" | ".join(depth_strs))

        line = " ".join(line_parts)
        print(line)
        self._log(line)

        if run:
            msg = (
                f"    [AGG RUN] {run['dir']} bias strengthening (net={run['net']:.1f}, "
                f"buy_share={run['share']*100:4.1f}%)"
            )
            print(msg)
            self._log(msg)

        if weak_msgs:
            msg = "    [WEAK OB] " + " ; ".join(weak_msgs)
            print(msg)
            self._log(msg)

        # 超简单即时方向触发：1s buy_share 门槛
        one_share = one["buy_share"] if one else 0.0
        if one_share > 0.5:
            sig = "    [SIG] 1s buy_share>50% -> LONG"
            print(sig)
            self._log(sig)
        elif one_share < 0.5:
            sig = "    [SIG] 1s buy_share<50% -> SHORT"
            print(sig)
            self._log(sig)

        self.last_emit = ts_now


def run_probe(symbol: str, ws_url: str, print_interval: float, log_file: str | None):
    topics = [
        f"publicTrade.{symbol}",
        f"orderbook.50.{symbol}",
        f"tickers.{symbol}",
    ]
    agg_tracker = AggFlowTracker(windows=[1.0, 3.0, 10.0])
    orderbook = OrderBookL2()
    reporter = ProbeReporter(
        agg_tracker,
        orderbook,
        print_interval=print_interval,
        log_file=log_file,
    )

    def on_open(ws):
        sub_msg = {"op": "subscribe", "args": topics}
        ws.send(json.dumps(sub_msg))
        print(f"[WS] subscribed to {topics}")

    def on_message(ws, message):
        try:
            data = json.loads(message)
            topic = data.get("topic", "")
            if not topic:
                return

            if topic.startswith("publicTrade"):
                trades = data.get("data") or []
                for t in trades:
                    ts = float(t.get("T", t.get("tradeTime", time.time() * 1000))) / 1000.0
                    price = float(t["p"])
                    vol = float(t["v"])
                    side = t["S"]
                    agg_tracker.add_trade(ts, side, vol)
                    reporter.last_price = price
                reporter.maybe_emit()

            elif topic.startswith("orderbook"):
                book_data = data.get("data")
                if not book_data:
                    return
                msg_type = data.get("type")
                if msg_type == "snapshot":
                    orderbook.apply_snapshot(book_data)
                else:
                    orderbook.apply_delta(book_data)
                reporter.maybe_emit()

            elif topic.startswith("tickers"):
                t = data.get("data") or {}
                if "lastPrice" in t:
                    try:
                        reporter.last_price = float(t["lastPrice"])
                    except Exception:
                        pass
                reporter.maybe_emit()

        except Exception as e:
            print("[WS ERROR]", e)
            traceback.print_exc()

    def on_error(ws, error):
        print("[WS ERROR]", error)

    def on_close(ws, code, msg):
        print(f"[WS] closed code={code} msg={msg}")

    while True:
        try:
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except KeyboardInterrupt:
            print("Interrupted, exit.")
            break
        except Exception as e:
            print("[WS LOOP] exception:", e)
            traceback.print_exc()
            time.sleep(5)

    if reporter.log_fp:
        try:
            reporter.log_fp.close()
        except Exception:
            pass


def parse_args():
    parser = argparse.ArgumentParser(description="Order book structure probe (Bybit)")
    parser.add_argument("--symbol", default="ETHUSDT", help="Bybit symbol, e.g., ETHUSDT")
    parser.add_argument(
        "--ws-url",
        default="wss://stream.bybit.com/v5/public/linear",
        help="Bybit public WS endpoint (choose linear/spot/inverse as needed)",
    )
    parser.add_argument(
        "--print-interval",
        type=float,
        default=1.0,
        help="Seconds between console pulses",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional path to append console pulses (txt).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_probe(
        symbol=args.symbol,
        ws_url=args.ws_url,
        print_interval=args.print_interval,
        log_file=args.log_file,
    )
