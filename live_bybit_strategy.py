import json
import time
import traceback
import threading
import os
import hmac
import hashlib
import requests

import websocket  # pip install websocket-client

from sweep_core import (
    Tick,
    Side,
    SweepModel,
    SweepSignal,
    SweepEventMeta,
    MeanReversionStrategy,
    StrategyActionType,
)

# ================== 日志配置 & 基本配置 ==================

LOG_PATH = os.getenv("LOG_PATH", "strategy.log")
log_fp = open(LOG_PATH, "a", buffering=1)


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"{ts} {msg}"
    print(line)
    try:
        log_fp.write(line + "\n")
    except Exception:
        pass

# ================== 基本配置 ==================

SYMBOL = "ETHUSDT"
WS_URL = "wss://stream.bybit.com/v5/public/linear"
TOPIC = f"publicTrade.{SYMBOL}"

# 运行模式："paper" 只打印信号；"live" 调你的实盘下单
MODE = "paper"

# 每次统一下单数量（真·实盘你自己改）
ORDER_QTY = 0.05  # ETH

# Bybit API 配置（仅 live 时使用）
BYBIT_BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_RECV_WINDOW = os.getenv("BYBIT_RECV_WINDOW", "5000")

# ======== Sweep 检测参数（和你 offline 用的那一套可以不同，先随便给一套） ========
SWEEP_SHORT_WIN_SEC = 0.30
SWEEP_LONG_WIN_SEC = 10.0
# 最松先触发：只要短期量略高于长期均值就触发
SWEEP_THRESHOLD_RATIO = 1.0  # 原 3.0 -> 1.2 -> 1.0

# ======== 策略本身参数（和 C++ 构造函数 4 个参数一一对应） ========
DELAY_MS = 5.0    # 近乎即时跟单
HOLD_SEC = 15.0   # 给更长观察时间
TP_BP    = 1.0    # 更紧的止盈，先锁利润
SL_BP    = 8.0    # 更宽的止损，容忍误触发回撤

# ================== C++ 实例 ==================

# 负责从 tick 中检测 sweep
sweep_model = SweepModel(
    short_window_sec=SWEEP_SHORT_WIN_SEC,
    long_window_sec=SWEEP_LONG_WIN_SEC,
    threshold_ratio=SWEEP_THRESHOLD_RATIO,
)

# 负责基于 sweep + tick 做反向均值回归
strategy = MeanReversionStrategy(
    delay_ms=DELAY_MS,
    hold_sec=HOLD_SEC,
    tp_bp=TP_BP,
    sl_bp=SL_BP,
)

# 当前仓位方向（只做 1 仓位的简单版本）
current_pos_dir = 0  # 0 = 无仓, +1 = long, -1 = short
entry_price_track = None
win_count = 0
loss_count = 0
cum_pnl = 0.0


# ================== 下单 / 平仓钩子 ==================

def _bybit_headers(payload_str: str):
    ts = str(int(time.time() * 1000))
    sign_str = ts + BYBIT_API_KEY + BYBIT_RECV_WINDOW + payload_str
    sign = hmac.new(BYBIT_API_SECRET.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-BAPI-API-KEY": BYBIT_API_KEY,
        "X-BAPI-SIGN": sign,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-RECV-WINDOW": BYBIT_RECV_WINDOW,
    }


def _ensure_keys():
    return bool(BYBIT_API_KEY and BYBIT_API_SECRET)


def place_order_live(direction: int, price: float, qty: float):
    side = "Buy" if direction > 0 else "Sell"
    payload = {
        "category": "linear",
        "symbol": SYMBOL,
        "side": side,
        "orderType": "Market",
        "timeInForce": "IOC",
        "qty": str(qty),
        "reduceOnly": False,
    }
    payload_str = json.dumps(payload, separators=(",", ":"))
    if not _ensure_keys():
        log(f"[LIVE ORDER MOCK] {side} {qty} {SYMBOL} @~{price} (缺少 API Key, 仅打印)")
        return
    try:
        headers = _bybit_headers(payload_str)
        url = f"{BYBIT_BASE_URL}/v5/order/create"
        resp = requests.post(url, headers=headers, data=payload_str, timeout=5)
        log(f"[LIVE ORDER] {side} {qty} {SYMBOL} @~{price} HTTP {resp.status_code} {resp.text}")
    except Exception as e:
        log(f"[LIVE ORDER ERROR] {e}")


def close_position_live(direction: int, price: float, qty: float):
    side = "Sell" if direction > 0 else "Buy"
    payload = {
        "category": "linear",
        "symbol": SYMBOL,
        "side": side,
        "orderType": "Market",
        "timeInForce": "IOC",
        "qty": str(qty),
        "reduceOnly": True,
    }
    payload_str = json.dumps(payload, separators=(",", ":"))
    if not _ensure_keys():
        log(f"[LIVE CLOSE MOCK] {side} {qty} {SYMBOL} @~{price} (缺少 API Key, 仅打印)")
        return
    try:
        headers = _bybit_headers(payload_str)
        url = f"{BYBIT_BASE_URL}/v5/order/create"
        resp = requests.post(url, headers=headers, data=payload_str, timeout=5)
        log(f"[LIVE CLOSE] {side} {qty} {SYMBOL} @~{price} HTTP {resp.status_code} {resp.text}")
    except Exception as e:
        log(f"[LIVE CLOSE ERROR] {e}")


def handle_action(act):
    """根据 C++ StrategyAction 执行操作"""
    global current_pos_dir, entry_price_track, win_count, loss_count, cum_pnl

    if act.type == StrategyActionType.Idle:
        return

    if act.type == StrategyActionType.OpenLong:
        log(f"[SIGNAL] OPEN LONG ts={act.ts:.3f} price={act.price}")
        if MODE == "live":
            if current_pos_dir != 0:
                log("[WARN] already in position, skip live open")
            else:
                place_order_live(+1, act.price, ORDER_QTY)
        current_pos_dir = +1
        entry_price_track = act.price

    elif act.type == StrategyActionType.OpenShort:
        log(f"[SIGNAL] OPEN SHORT ts={act.ts:.3f} price={act.price}")
        if MODE == "live":
            if current_pos_dir != 0:
                log("[WARN] already in position, skip live open")
            else:
                place_order_live(-1, act.price, ORDER_QTY)
        current_pos_dir = -1
        entry_price_track = act.price

    elif act.type == StrategyActionType.Close:
        if entry_price_track is not None and current_pos_dir != 0:
            pnl = (act.price - entry_price_track) * current_pos_dir
            cum_pnl += pnl
            if pnl > 0:
                win_count += 1
            elif pnl < 0:
                loss_count += 1
            total_trades = win_count + loss_count if (win_count + loss_count) > 0 else 1
            win_rate = win_count / total_trades
            log(f"[PNL] close mark_pnl={pnl:.4f}, cum_pnl={cum_pnl:.4f}, "
                f"win_rate={win_rate*100:4.1f}% (wins={win_count}, losses={loss_count})")
        log(f"[SIGNAL] CLOSE dir={act.dir} ts={act.ts:.3f} price={act.price}")
        if MODE == "live":
            if current_pos_dir == 0:
                log("[WARN] no position recorded, skip live close")
            else:
                close_position_live(act.dir, act.price, ORDER_QTY)
        current_pos_dir = 0
        entry_price_track = None


# ================== WebSocket 回调 ==================

def on_open(ws):
    log("WS opened")
    sub_msg = {
        "op": "subscribe",
        "args": [TOPIC],
    }
    ws.send(json.dumps(sub_msg))
    log(f"Subscribed: {TOPIC}")


def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("topic") != TOPIC:
            return
        trades = data.get("data") or []
        if not trades:
            return

        for t in trades:
            # Bybit publicTrade v5
            ts = float(t["T"]) / 1000.0
            price = float(t["p"])
            vol = float(t["v"])
            side = Side.Buy if t["S"] == "Buy" else Side.Sell

            # 1) tick 喂给 SweepModel 做 sweep 检测
            tick = Tick()
            tick.timestamp = ts
            tick.price = price
            tick.volume = vol
            tick.side = side

            sig = sweep_model.process_tick(tick)

            if sig != SweepSignal.NoSignal:
                ev = sweep_model.get_last_event()  # SweepEventMeta
                log(f"[SWEEP] sig={sig.name} dir={ev.direction} "
                    f"ts={ev.ts_end:.3f} price_end={ev.price_end} vol={ev.volume_total:.2f}")
                # 这一步是 “sweep 触发 → 反向均值回归 策略的 on_sweep”
                act_from_sweep = strategy.on_sweep(ev)
                if act_from_sweep.type != StrategyActionType.Idle:
                    log(f"[ACT] from_sweep {act_from_sweep}")
                handle_action(act_from_sweep)

            # 2) 无论是否有 sweep，都给策略一个 on_tick 用来管理持仓
            #    注意：这里 C++ 的 on_tick(ts, price) 只吃两个 double
            act_from_tick = strategy.on_tick(ts, price)
            if act_from_tick.type != StrategyActionType.Idle:
                log(f"[ACT] from_tick {act_from_tick}")
            handle_action(act_from_tick)

    except Exception as e:
        log(f"[WS ERROR] exception in on_message: {e}")
        traceback.print_exc()


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
            log("Interrupted, exiting ws loop")
            break
        except Exception as e:
            log(f"[WS LOOP] exception: {e}")
            traceback.print_exc()
            time.sleep(5)


def main():
    log(f"Starting live strategy for {SYMBOL}, MODE={MODE}")
    ws_thread = threading.Thread(target=ws_loop, daemon=True)
    ws_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("Main loop interrupted, exit.")


if __name__ == "__main__":
    main()
