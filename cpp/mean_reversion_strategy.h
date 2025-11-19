#pragma once
#include <cstdint>
#include "sweep_model.h"

// 行为类型：避免使用 None
enum class StrategyActionType : uint8_t {
    Idle = 0,      // 不要用 None！
    OpenLong = 1,
    OpenShort = 2,
    Close = 3
};

struct StrategyAction {
    StrategyActionType type = StrategyActionType::Idle;
    int dir = 0;     // 1=long, -1=short
    double price = 0.0;
    double ts = 0.0;
};

// === 反 Sweep 均值回归策略 ===
class MeanReversionStrategy {
public:
    double delay_ms;
    double hold_sec;
    double tp_bp;     // 止盈
    double sl_bp;     // 止损

    bool in_position = false;
    int pos_dir = 0;  // 1=long, -1=short
    double entry_price = 0.0;
    double entry_ts = 0.0;

    MeanReversionStrategy(
        double delay_ms_ = 80.0,
        double hold_sec_ = 5.0,
        double tp_bp_ = 2.0,
        double sl_bp_ = 2.0
    ) :
        delay_ms(delay_ms_),
        hold_sec(hold_sec_),
        tp_bp(tp_bp_),
        sl_bp(sl_bp_)
    {}

    StrategyAction on_sweep(const SweepEventMeta& ev);
    StrategyAction on_tick(double ts, double price);

private:
    void clear_position();
};
