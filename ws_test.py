import json
import time
import threading
import csv
import websocket

from sweep_core import SweepModel, Tick, Side, SweepSignal

WS_URL = "wss://stream.bybit.com/v5/public/linear"

model = SweepModel(
    short_window_sec=0.3,   # 事件窗口 ~300ms
    long_window_sec=10.0,
    threshold_ratio=3.0,
)

tick_log = open("ticks_eth.csv", "w", newline="")
tick_writer = csv.writer(tick_log)
tick_writer.writerow(["ts", "price", "volume", "side"])  # side: B/S

sweep_log = open("sweeps_eth.csv", "w", newline="")
sweep_writer = csv.writer(sweep_log)
sweep_writer.writerow(["ts_start", "ts_end", "direction",
                       "price_start", "price_end", "volume_total"])

def on_open(ws):
    print("WS opened")
    sub_msg = {
        "op": "subscribe",
        "args": [
            "publicTrade.ETHUSDT",
        ],
    }
    ws.send(json.dumps(sub_msg))
    print("Subscribed to publicTrade.ETHUSDT")

def on_message(ws, message: str):
    msg = json.loads(message)
    topic = msg.get("topic", "")
    if not topic.startswith("publicTrade."):
        return

    data = msg.get("data", [])
    for t in data:
        tick = Tick()
        tick.timestamp = t["T"] / 1000.0
        tick.price = float(t["p"])
        tick.volume = float(t["v"])
        tick.side = Side.Buy if t["S"] == "Buy" else Side.Sell

        # 写 tick
        tick_writer.writerow([
            tick.timestamp,
            tick.price,
            tick.volume,
            "B" if tick.side == Side.Buy else "S",
        ])

        sig = model.process_tick(tick)

        if sig != SweepSignal.NoSignal:
            ev = model.get_last_event()
            if ev.direction == 0:
                continue  # 双边放量，忽略
            sweep_writer.writerow([
                ev.ts_start,
                ev.ts_end,
                ev.direction,
                ev.price_start,
                ev.price_end,
                ev.volume_total,
            ])
            tick_log.flush()
            sweep_log.flush()

            print(
                f"[SWEEP] dir={ev.direction} "
                f"price {ev.price_start:.2f}->{ev.price_end:.2f} "
                f"vol={ev.volume_total:.3f} "
                f"ts_start={ev.ts_start:.3f}, ts_end={ev.ts_end:.3f}"
            )

def on_error(ws, error):
    print("WS error:", error)

def on_close(ws, code, msg):
    print(f"WS closed: code={code}, msg={msg}")
    tick_log.close()
    sweep_log.close()

def ping_loop(ws):
    while True:
        time.sleep(20)
        try:
            ws.send(json.dumps({"op": "ping", "req_id": "keepalive"}))
        except Exception as e:
            print("Ping failed:", e)
            break

if __name__ == "__main__":
    websocket.enableTrace(False)

    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    t_ws = threading.Thread(target=ws.run_forever, kwargs={"ping_interval": None})
    t_ws.daemon = True
    t_ws.start()

    t_ping = threading.Thread(target=ping_loop, args=(ws,))
    t_ping.daemon = True
    t_ping.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Interrupted, closing WS...")
        ws.close()
        tick_log.close()
        sweep_log.close()
