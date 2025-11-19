// cpp/sweep_model.cpp
#include "sweep_model.h"

SweepModel::SweepModel(double short_window_sec,
                       double long_window_sec,
                       double threshold_ratio)
    : short_win_(short_window_sec),
      long_win_(long_window_sec),
      threshold_ratio_(threshold_ratio),
      short_buy_vol_(0.0),
      short_sell_vol_(0.0),
      long_buy_vol_(0.0),
      long_sell_vol_(0.0),
      in_sweep_(false),
      last_sweep_ts_(0.0),
      last_price_(0.0),
      has_last_price_(false)
{
    last_event_.ts_start    = 0.0;
    last_event_.ts_end      = 0.0;
    last_event_.price_start = 0.0;
    last_event_.price_end   = 0.0;
    last_event_.volume_total = 0.0;
    last_event_.direction   = 0;
}

void SweepModel::evict_old(double current_ts) {
    // 移出 long_window 之外的 tick，并更新 long_* 和 short_* 统计
    while (!window_.empty() &&
           current_ts - window_.front().timestamp > long_win_) {
        const Tick& t = window_.front();
        double vol = t.volume;
        if (t.side == Side::Buy) {
            long_buy_vol_  -= vol;
            if (current_ts - t.timestamp <= short_win_) {
                short_buy_vol_ -= vol;
            }
        } else {
            long_sell_vol_ -= vol;
            if (current_ts - t.timestamp <= short_win_) {
                short_sell_vol_ -= vol;
            }
        }
        window_.pop_front();
    }

    // 简化版：short window 我只在添加新 tick 时累加，
    // old tick 超出 short_win_ 后的精确减法可以通过更复杂结构实现；
    // 这里先以“短窗口<<长窗口”的近似。
}

SweepSignal SweepModel::process_tick(const Tick& tick) {
    double ts = tick.timestamp;

    // 先驱逐过期 tick
    evict_old(ts);

    // 更新 last_price_（用上一个 tick 的 price）
    if (!has_last_price_) {
        last_price_ = tick.price;
        has_last_price_ = true;
    }

    // 将当前 tick 加入窗口并更新统计量
    window_.push_back(tick);
    double vol = tick.volume;
    if (tick.side == Side::Buy) {
        short_buy_vol_ += vol;
        long_buy_vol_  += vol;
    } else {
        short_sell_vol_ += vol;
        long_sell_vol_  += vol;
    }

    double short_total = short_buy_vol_ + short_sell_vol_;
    double long_total  = long_buy_vol_  + long_sell_vol_;
    if (long_total <= 0.0) {
        last_price_ = tick.price;
        return SweepSignal::NoSignal;
    }

    // “短期量 / 长期平均量”的粗近似
    double expected_short = (long_total / long_win_) * short_win_;
    if (expected_short <= 0.0) {
        last_price_ = tick.price;
        return SweepSignal::NoSignal;
    }
    double ratio = short_total / expected_short;

    // 当 ratio 明显回落，允许下一次 sweep
    if (ratio < threshold_ratio_ * 0.5) {
        in_sweep_ = false;
    }

    // 已处于 sweep 状态：不再重复触发
    if (in_sweep_) {
        last_price_ = tick.price;
        return SweepSignal::NoSignal;
    }

    // 只在 ratio 第一次跨越阈值时触发事件
    if (ratio >= threshold_ratio_) {
        // 进入 sweep 状态
        in_sweep_ = true;
        last_sweep_ts_ = ts;

        // 判断方向
        SweepSignal sig = SweepSignal::NoSignal;
        double buy = short_buy_vol_;
        double sell = short_sell_vol_;

        if (buy > sell * 1.5) {
            sig = SweepSignal::UpSweep;
            last_event_.direction = 1;
        } else if (sell > buy * 1.5) {
            sig = SweepSignal::DownSweep;
            last_event_.direction = -1;
        } else {
            last_event_.direction = 0;
        }

        if (sig != SweepSignal::NoSignal) {
            // 填充事件元信息
            last_event_.ts_end      = ts;
            last_event_.ts_start    = ts - short_win_;    // 近似窗口起点
            last_event_.price_end   = tick.price;
            last_event_.price_start = has_last_price_ ? last_price_ : tick.price;
            last_event_.volume_total = short_total;
        }

        last_price_ = tick.price;
        return sig;
    }

    last_price_ = tick.price;
    return SweepSignal::NoSignal;
}
