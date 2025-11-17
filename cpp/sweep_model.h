// cpp/sweep_model.h
#pragma once
#include <deque>

enum class Side {
    Buy = 1,
    Sell = -1
};

enum class SweepSignal {
    NoSignal = 0,
    UpSweep = 1,
    DownSweep = -1
};

struct Tick {
    double timestamp;   // 秒，比如 1700000000.123
    double price;
    double volume;      // 成交量
    Side   side;        // taker 买/卖
};

class SweepModel {
public:
    SweepModel(double short_window_sec = 2.0,
               double long_window_sec  = 20.0,
               double threshold_ratio  = 3.0);

    // 喂一条 tick，返回本 tick 是否触发 sweep 信号
    SweepSignal process_tick(const Tick& tick);

private:
    double short_win_;
    double long_win_;
    double threshold_ratio_;

    std::deque<Tick> window_;   // 保存最近 long_window_sec 内的 tick

    double short_buy_vol_;
    double short_sell_vol_;
    double long_buy_vol_;
    double long_sell_vol_;

    void evict_old(double current_ts);
};
