"""
WebSocket smoke test v2:
- Subscribe trades
- Compute 1s buy/sell share and emit LONG when buy_share>50%, SHORT when <50%
目的：快速验证 WS 数据链路和最简单的方向逻辑。
"""

import json
import threading
import time
from collections import deque
import os

import websocket  # pip install websocket-client

SYMBOL = "ETHUSDT"
WS_URL = "wss://stream.bybit.com/v5/public/linear"
TOPIC = f"publicTrade.{SYMBOL}"

trades_1s: deque[tuple] = deque()  # (ts, side, vol, price)
bucket_1s: deque[dict] = deque(maxlen=6)  # [{sec, buy, sell, net}]
current_pos_dir = 0  # smoke 模式也维护一个伪仓位状态
entry_price = None
cum_pnl = 0.0
win_count = 0
loss_count = 0
EQUITY = float(os.getenv("SMOKE_EQUITY", "20000"))  # 初始净值 USD
LEVERAGE = float(os.getenv("SMOKE_LEVERAGE", "100.0"))  # 默认 100x
position_size_usd = 0.0
bankroll = EQUITY  # 随收益滚动的本金
LOG_PATH = os.getenv("SMOKE_LOG_PATH", "smoke_test.log")
log_fp = open(LOG_PATH, "a", buffering=1)


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"{ts} {msg}"
    print(line)
    try:
        log_fp.write(line + "\n")
    except Exception:
        pass


class ActionType:
    Idle = "Idle"
    OpenLong = "OpenLong"
    OpenShort = "OpenShort"
    Close = "Close"


def handle_action(act):
    """纸面执行：打印信号并维护 current_pos_dir"""
    global current_pos_dir, entry_price, cum_pnl, win_count, loss_count, position_size_usd, bankroll
    if act["type"] == ActionType.Idle:
        return
    if act["type"] == ActionType.OpenLong:
        log(f"[SIGNAL] OPEN LONG ts={act['ts']:.3f} price={act['price']}")
        current_pos_dir = +1
        entry_price = act["price"]
        position_size_usd = bankroll * LEVERAGE  # 本金+收益 滚动后全仓杠杆
    elif act["type"] == ActionType.OpenShort:
        log(f"[SIGNAL] OPEN SHORT ts={act['ts']:.3f} price={act['price']}")
        current_pos_dir = -1
        entry_price = act["price"]
        position_size_usd = bankroll * LEVERAGE
    elif act["type"] == ActionType.Close:
        if current_pos_dir != 0 and entry_price is not None:
            # PnL 按 USD 计：方向 * 价格变动比例 * 名义
            pnl = (act["price"] - entry_price) / entry_price * position_size_usd * current_pos_dir
            cum_pnl += pnl
            bankroll += pnl  # 滚入下一次本金
            if pnl > 0:
                win_count += 1
            elif pnl < 0:
                loss_count += 1
            total_trades = win_count + loss_count if (win_count + loss_count) > 0 else 1
            win_rate = win_count / total_trades
            log(f"[PNL] close mark_pnl={pnl:.4f}, cum_pnl={cum_pnl:.4f} "
                f"win_rate={win_rate*100:4.1f}% (wins={win_count}, losses={loss_count}), "
                f"bankroll={bankroll:.2f}")
        log(f"[SIGNAL] CLOSE dir={act['dir']} ts={act['ts']:.3f} price={act['price']}")
        current_pos_dir = 0
        entry_price = None
        position_size_usd = 0.0


def on_open(ws):
    log("WS opened")
    ws.send(json.dumps({"op": "subscribe", "args": [TOPIC]}))
    log(f"Subscribed: {TOPIC}")


def on_message(ws, message):
    data = json.loads(message)
    if data.get("topic") != TOPIC:
        return
    trades = data.get("data") or []
    if not trades:
        return

    ts_now = time.time()
    for t in trades:
        ts = float(t["T"]) / 1000.0
        side = t["S"]
        vol = float(t["v"])
        price_t = float(t["p"])
        trades_1s.append((ts, side, vol, price_t))

        sec = int(ts)
        if not bucket_1s or bucket_1s[-1]["sec"] != sec:
            bucket_1s.append({"sec": sec, "buy": 0.0, "sell": 0.0})
        if side == "Buy":
            bucket_1s[-1]["buy"] += vol
        else:
            bucket_1s[-1]["sell"] += vol

    # prune >1s
    cutoff = ts_now - 1.0
    while trades_1s and trades_1s[0][0] < cutoff:
        trades_1s.popleft()
    cutoff_sec = int(ts_now) - 5
    while bucket_1s and bucket_1s[0]["sec"] < cutoff_sec:
        bucket_1s.popleft()

    buy = sum(v for _, s, v, _ in trades_1s if s == "Buy")
    sell = sum(v for _, s, v, _ in trades_1s if s == "Sell")
    total = buy + sell
    buy_share = buy / total if total > 0 else 0.0

    # 粗略估计当前 bid/ask：用本批次的买单最高价当 bid，卖单最低价当 ask
    bid_prices = [float(t["p"]) for t in trades if t["S"] == "Buy"]
    ask_prices = [float(t["p"]) for t in trades if t["S"] == "Sell"]
    cur_bid = max(bid_prices) if bid_prices else None
    cur_ask = min(ask_prices) if ask_prices else None
    spread = (cur_ask - cur_bid) if (cur_bid is not None and cur_ask is not None) else None

    first = trades[0]
    price = float(first["p"])
    spread_str = f" spread={spread:.2f}" if spread is not None else ""
    log(f"[WS OK] recv {len(trades)} trades, 1s buy={buy:.2f} sell={sell:.2f} "
        f"({buy_share*100:4.1f}% buy){spread_str}")

    ts_sig = time.time()
    # 3 个最近 1s 桶同向且净额递增 -> 作为“主动方向一致+增强”触发
    run_dir = None
    if len(bucket_1s) >= 3:
        b1, b2, b3 = bucket_1s[-3], bucket_1s[-2], bucket_1s[-1]
        def bucket_dir(bk):
            net = bk["buy"] - bk["sell"]
            tot = bk["buy"] + bk["sell"]
            if tot <= 0:
                return None, 0.0
            share = bk["buy"] / tot
            if net > 0 and share >= 0.6:
                return "buy", abs(net)
            if net < 0 and share <= 0.4:
                return "sell", abs(net)
            return None, 0.0
        d1,m1 = bucket_dir(b1); d2,m2 = bucket_dir(b2); d3,m3 = bucket_dir(b3)
        if d1 and d1==d2==d3 and m1<=m2<=m3:
            run_dir = d3

    if run_dir:
        log(f"[AGG RUN] dir={run_dir} buckets={[(bucket_1s[-3]['buy'], bucket_1s[-3]['sell']), (bucket_1s[-2]['buy'], bucket_1s[-2]['sell']), (bucket_1s[-1]['buy'], bucket_1s[-1]['sell'])]}")

    # 信号：优先 AGG RUN，否则简单 1s buy_share>50/<50；切换方向时先平
    desired_dir = None
    if run_dir == "buy":
        desired_dir = 1
    elif run_dir == "sell":
        desired_dir = -1
    else:
        if buy_share > 0.5 and total > 0:
            desired_dir = 1
        elif buy_share < 0.5 and total > 0:
            desired_dir = -1

    if desired_dir == 1:
        if current_pos_dir == -1:
            handle_action({"type": ActionType.Close, "dir": -1, "ts": ts_sig, "price": price})
        if current_pos_dir != 1:
            handle_action({"type": ActionType.OpenLong, "dir": 1, "ts": ts_sig, "price": price})
    elif desired_dir == -1:
        if current_pos_dir == 1:
            handle_action({"type": ActionType.Close, "dir": 1, "ts": ts_sig, "price": price})
        if current_pos_dir != -1:
            handle_action({"type": ActionType.OpenShort, "dir": -1, "ts": ts_sig, "price": price})


def on_error(ws, error):
    log(f"[WS ERROR] {error}")


def on_close(ws, code, msg):
    log(f"WS closed: code={code}, msg={msg}")


def ws_loop():
    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except KeyboardInterrupt:
            log("Interrupted, exit.")
            break
        except Exception as e:
            log(f"[WS LOOP] exception: {e}")
            time.sleep(5)


if __name__ == "__main__":
    log(f"Starting WS smoke test for {SYMBOL}")
    t = threading.Thread(target=ws_loop, daemon=True)
    t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("Main loop interrupted.")
