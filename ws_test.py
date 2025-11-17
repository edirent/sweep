import json
import time
import threading
import websocket

from sweep_core import SweepModel, Tick, Side, SweepSignal

WS_URL = "wss://stream.bybit.com/v5/public/linear"

model = SweepModel(
    short_window_sec=2.0,
    long_window_sec=20.0,
    threshold_ratio=3.0,
)

def on_open(ws):
    print("WS opened")
    sub_msg = {
        "op": "subscribe",
        "args": [
            "publicTrade.ETHUSDT",  # 你也可以改 BTCUSDT 等
        ],
    }
    ws.send(json.dumps(sub_msg))
    print("Subscribed to publicTrade.ETHUSDT")

def on_message(ws, message: str):
    msg = json.loads(message)

    # 只处理 trade 消息
    topic = msg.get("topic", "")
    if not topic.startswith("publicTrade."):
        return

    data = msg.get("data", [])
    for t in data:
        # Bybit publicTrade 响应示例字段：T 时间戳 ms, p 价格, v 成交量, S 买卖方向:contentReference[oaicite:2]{index=2}
        tick = Tick()
        tick.timestamp = t["T"] / 1000.0
        tick.price = float(t["p"])
        tick.volume = float(t["v"])
        tick.side = Side.Buy if t["S"] == "Buy" else Side.Sell

        sig = model.process_tick(tick)
        if sig != SweepSignal.NoSignal:
            print(
                f"[SWEEP] sig={sig} price={tick.price} ts={tick.timestamp} "
                f"vol={tick.volume} side={tick.side}"
            )

def on_error(ws, error):
    print("WS error:", error)

def on_close(ws, code, msg):
    print(f"WS closed: code={code}, msg={msg}")

def ping_loop(ws):
    # 官方建议 20s 发一次 ping 保持连接:contentReference[oaicite:3]{index=3}
    while True:
        time.sleep(20)
        try:
            ws.send(json.dumps({"op": "ping", "req_id": "keepalive"}))
        except Exception as e:
            print("Ping failed, stop ping loop:", e)
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

    # 开一个线程跑 WS
    t_ws = threading.Thread(target=ws.run_forever, kwargs={"ping_interval": None})
    t_ws.daemon = True
    t_ws.start()

    # 再开一个线程手动发 ping
    t_ping = threading.Thread(target=ping_loop, args=(ws,))
    t_ping.daemon = True
    t_ping.start()

    # 主线程挂起等待
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Interrupted by user, closing WS...")
        ws.close()
