// cpp/sweep_model.h
#pragma once
#include <deque>

enum class Side {
    Buy = 1,
    Sell = -1
};

enum class SweepSignal {
    NoSignal = 0,
    UpSweep  = 1,
    DownSweep = -1
};

struct Tick {
    double timestamp;   // 秒
    double price;
    double volume;
    Side   side;
};

// 单次 sweep 事件的元信息（给 Python 用）
struct SweepEventMeta {
    double ts_start;     // 事件起始时间（约等于窗口开始）
    double ts_end;       // 事件结束时间（触发时刻）
    double price_start;  // 窗口开始时价格（近似）
    double price_end;    // 触发时价格
    double volume_total; // 窗口内总成交量
    int    direction;    // 1=Up, -1=Down
};

class SweepModel {
public:
    SweepModel(double short_window_sec = 0.3,   // 典型 sweep 时间窗：0.1~0.5s
               double long_window_sec  = 10.0,  // 长期参考：几秒到几十秒
               double threshold_ratio  = 3.0);

    // 喂一条 tick，若触发 sweep，则返回 UpSweep/DownSweep，否则 NoSignal
    SweepSignal process_tick(const Tick& tick);

    // 返回最近一次触发的 sweep 事件信息（若无，direction=0）
    SweepEventMeta get_last_event() const { return last_event_; }

private:
    double short_win_;
    double long_win_;
    double threshold_ratio_;

    // 两层窗口：长窗口用于基线，短窗口用于即时爆发
    std::deque<Tick> window_long_;   // 保存最近 long_window_sec 内的 tick
    std::deque<Tick> window_short_;  // 保存最近 short_window_sec 内的 tick

    double short_buy_vol_;
    double short_sell_vol_;
    double long_buy_vol_;
    double long_sell_vol_;

    // 去抖/状态
    bool   in_sweep_;
    double last_sweep_ts_;

    // 上一个价格（用于估计 price_start）
    double last_price_;
    bool   has_last_price_;

    // 最近一次触发的 sweep 事件
    SweepEventMeta last_event_;

    void evict_old(double current_ts);
};
