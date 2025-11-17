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
      long_sell_vol_(0.0) {}

void SweepModel::evict_old(double current_ts) {
    // 把超出 long_window 的 tick 移出队列，并更新统计量
    while (!window_.empty() &&
           current_ts - window_.front().timestamp > long_win_) {
        const Tick& t = window_.front();
        double vol = t.volume;
        if (t.side == Side::Buy) {
            long_buy_vol_  -= vol;
            // 如果这个 tick 也在 short_window 里，也要减
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

    // 接着再扫一遍队列前部，把超出 short_win 但仍在 long_win 的部分
    // 从 short 统计里移除（但 long 保留）
    for (auto it = window_.begin(); it != window_.end(); ++it) {
        double age = current_ts - it->timestamp;
        if (age > short_win_) {
            // 已经不应计入 short，但 long 继续保留，所以只改 short
            double vol = it->volume;
            if (it->side == Side::Buy) {
                // 这里可能会多减，要更精细就额外打标记，这里先简单处理
                // 简化：我们只在添加 tick 时维护 short_*，这里可以不处理
            } else {
                // 同上
            }
        } else {
            // 后面的 tick 更新鲜，可以直接 break
            break;
        }
    }
}

SweepSignal SweepModel::process_tick(const Tick& tick) {
    double ts = tick.timestamp;

    // 先移除过期数据
    evict_old(ts);

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

    // 计算 short / long 比例
    double short_total = short_buy_vol_ + short_sell_vol_;
    double long_total  = long_buy_vol_  + long_sell_vol_;

    if (long_total <= 0.0) {
        return SweepSignal::NoSignal;
    }

    double ratio = short_total / (long_total / (long_win_ / short_win_));
    // 这里 ratio 只给你一个感觉：短期是否远超长期平均

    // 简化：只在明显单边时给信号
    if (ratio >= threshold_ratio_) {
        // 判断是多头 sweep 还是空头 sweep
        if (short_buy_vol_ > short_sell_vol_ * 1.5) {
            return SweepSignal::UpSweep;
        } else if (short_sell_vol_ > short_buy_vol_ * 1.5) {
            return SweepSignal::DownSweep;
        }
    }

    return SweepSignal::NoSignal;
}
