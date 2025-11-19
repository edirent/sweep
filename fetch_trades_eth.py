import csv
import time
import requests

SYMBOL   = "ETHUSDT"
CATEGORY = "linear"       # 你现在用的是哪个就填哪个: "spot" / "linear" / "inverse"
OUT_PATH = "ticks_eth_hist.csv"
LIMIT    = 1000           # Bybit 单次上限
TARGET   = 100_000        # 至少拉 10 万条

BASE_URL = "https://api.bybit.com"


def fetch_once(cursor: str | None):
    params = {
        "category": CATEGORY,
        "symbol": SYMBOL,
        "limit": LIMIT,
    }
    if cursor:
        params["cursor"] = cursor

    resp = requests.get(f"{BASE_URL}/v5/market/recent-trade", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit error: {data}")

    result = data["result"]
    trades = result.get("list", [])
    next_cursor = result.get("nextPageCursor")
    return trades, next_cursor


def parse_trade(t: dict):
    # 时间戳
    if "T" in t:
        ts = int(t["T"]) / 1000.0
    elif "time" in t:
        ts = int(t["time"]) / 1000.0
    elif "execTime" in t:
        ts = int(t["execTime"]) / 1000.0
    else:
        raise ValueError(f"Unknown timestamp field: {t}")

    # 价格
    if "p" in t:
        price = float(t["p"])
    elif "price" in t:
        price = float(t["price"])
    elif "execPrice" in t:
        price = float(t["execPrice"])
    else:
        raise ValueError(f"Unknown price field: {t}")

    # 量
    if "v" in t:
        vol = float(t["v"])
    elif "size" in t:
        vol = float(t["size"])
    elif "execQty" in t:
        vol = float(t["execQty"])
    else:
        raise ValueError(f"Unknown volume field: {t}")

    # 方向
    if "S" in t:
        side = "B" if t["S"] == "Buy" else "S"
    elif "side" in t:
        side = "B" if t["side"].upper() == "BUY" else "S"
    elif "isBuyerMaker" in t:
        # taker = not maker
        maker = t["isBuyerMaker"]
        side = "S" if maker else "B"
    else:
        raise ValueError(f"Unknown side field: {t}")

    return ts, price, vol, side


def main():
    cursor = None
    total = 0

    with open(OUT_PATH, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "price", "volume", "side"])

        while total < TARGET:
            trades, cursor = fetch_once(cursor)
            if not trades:
                print("[INFO] no more trades from API")
                break

            # 注意：Bybit 返回通常是时间倒序
            for t in trades:
                ts, price, vol, side = parse_trade(t)
                w.writerow([ts, price, vol, side])
                total += 1

            print(f"[INFO] fetched={len(trades)}, total={total}")

            if not cursor:
                print("[INFO] no cursor, stop")
                break

            time.sleep(0.1)

    print(f"[DONE] wrote {total} trades to {OUT_PATH}")


if __name__ == "__main__":
    main()
