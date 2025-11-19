import json
import time
import traceback
import threading

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

# ================== 基本配置 ==================

SYMBOL = "ETHUSDT"
WS_URL = "wss://stream.bybit.com/v5/public/linear"
TOPIC = f"publicTrade.{SYMBOL}"

# 运行模式："paper" 只打印信号；"live" 调你的实盘下单
MODE = "paper"

# 每次统一下单数量（真·实盘你自己改）
ORDER_QTY = 0.05  # ETH

# ======== Sweep 检测参数（和你 offline 用的那一套可以不同，先随便给一套） ========
SWEEP_SHORT_WIN_SEC = 0.30
SWEEP_LONG_WIN_SEC = 10.0
SWEEP_THRESHOLD_RATIO = 3.0  # 这个是 sweep_model 里用的 ratio

# ======== 策略本身参数（和 C++ 构造函数 4 个参数一一对应） ========
DELAY_MS = 80.0   # sweep 后延迟入场（毫秒）
HOLD_SEC = 10.0   # 最大持仓时间
TP_BP    = 2.0    # 止盈（bp）
SL_BP    = 5.0    # 止损（bp）

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


# ================== 下单 / 平仓钩子 ==================

def place_order_live(direction: int, price: float, qty: float):
    side = "Buy" if direction > 0 else "Sell"
    print(f"[LIVE ORDER] {side} {qty} {SYMBOL} @~{price}  <<< TODO: 实现你自己的 REST 调用")
    # TODO: /v5/order/create 之类的自己写


def close_position_live(direction: int, price: float, qty: float):
    side = "Sell" if direction > 0 else "Buy"
    print(f"[LIVE CLOSE] {side} {qty} {SYMBOL} @~{price}  <<< TODO: 实现你自己的 REST 调用")
    # TODO: 真正平仓逻辑自己写


def handle_action(act):
    """根据 C++ StrategyAction 执行操作"""
    global current_pos_dir

    if act.type == StrategyActionType.Idle:
        return

    if act.type == StrategyActionType.OpenLong:
        print(f"[SIGNAL] OPEN LONG ts={act.ts:.3f} price={act.price}")
        if MODE == "live":
            if current_pos_dir != 0:
                print("[WARN] already in position, skip live open")
            else:
                place_order_live(+1, act.price, ORDER_QTY)
        current_pos_dir = +1

    elif act.type == StrategyActionType.OpenShort:
        print(f"[SIGNAL] OPEN SHORT ts={act.ts:.3f} price={act.price}")
        if MODE == "live":
            if current_pos_dir != 0:
                print("[WARN] already in position, skip live open")
            else:
                place_order_live(-1, act.price, ORDER_QTY)
        current_pos_dir = -1

    elif act.type == StrategyActionType.Close:
        print(f"[SIGNAL] CLOSE dir={act.dir} ts={act.ts:.3f} price={act.price}")
        if MODE == "live":
            if current_pos_dir == 0:
                print("[WARN] no position recorded, skip live close")
            else:
                close_position_live(act.dir, act.price, ORDER_QTY)
        current_pos_dir = 0


# ================== WebSocket 回调 ==================

def on_open(ws):
    print("WS opened")
    sub_msg = {
        "op": "subscribe",
        "args": [TOPIC],
    }
    ws.send(json.dumps(sub_msg))
    print("Subscribed:", TOPIC)


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
                # 这一步是 “sweep 触发 → 反向均值回归 策略的 on_sweep”
                act_from_sweep = strategy.on_sweep(ev)
                handle_action(act_from_sweep)

            # 2) 无论是否有 sweep，都给策略一个 on_tick 用来管理持仓
            #    注意：这里 C++ 的 on_tick(ts, price) 只吃两个 double
            act_from_tick = strategy.on_tick(ts, price)
            handle_action(act_from_tick)

    except Exception as e:
        print("[WS ERROR] exception in on_message:", e)
        traceback.print_exc()


def on_error(ws, error):
    print("[WS ERROR]", error)


def on_close(ws, code, msg):
    print(f"WS closed: code={code}, msg={msg}")


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
            print("Interrupted, exiting ws loop")
            break
        except Exception as e:
            print("[WS LOOP] exception:", e)
            traceback.print_exc()
            time.sleep(5)


def main():
    print(f"Starting live strategy for {SYMBOL}, MODE={MODE}")
    ws_thread = threading.Thread(target=ws_loop, daemon=True)
    ws_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Main loop interrupted, exit.")


if __name__ == "__main__":
    main()
