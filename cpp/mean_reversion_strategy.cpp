#include "mean_reversion_strategy.h"

StrategyAction MeanReversionStrategy::on_sweep(const SweepEventMeta& ev) {
    StrategyAction act;

    if (in_position) {
        // A second sweep in the original direction indicates continuation;
        // close the current position as a stop-loss.
        if (ev.direction != 0 && ev.direction == -pos_dir) {
            act.type = StrategyActionType::Close;
            act.dir = pos_dir;
            act.price = ev.price_end;
            act.ts = ev.ts_end;
            clear_position();
        }
        return act;
    }

    double delay_sec = delay_ms / 1000.0;
    double ts_enter = ev.ts_end + delay_sec;

    act.ts = ts_enter;

    if (ev.direction > 0) {
        act.type = StrategyActionType::OpenShort;
        act.dir = -1;
    } else if (ev.direction < 0) {
        act.type = StrategyActionType::OpenLong;
        act.dir = 1;
    } else {
        // No clear sweep direction -> stay idle.
        return act;
    }

    act.price = ev.price_end;

    // Track the new position for subsequent on_tick evaluations.
    in_position = true;
    pos_dir = act.dir;
    entry_price = act.price;
    entry_ts = act.ts;

    return act;
}

StrategyAction MeanReversionStrategy::on_tick(double ts, double price) {
    StrategyAction act;

    if (!in_position) return act;

    double ret = (price - entry_price) / entry_price * 10000.0;

    if (pos_dir == 1 && ret >= tp_bp) {
        act.type = StrategyActionType::Close;
        act.dir = pos_dir;
        act.ts = ts;
        act.price = price;
        clear_position();
        return act;
    }

    if (pos_dir == -1 && -ret >= tp_bp) {
        act.type = StrategyActionType::Close;
        act.dir = pos_dir;
        act.ts = ts;
        act.price = price;
        clear_position();
        return act;
    }

    if (pos_dir == 1 && -ret >= sl_bp) {
        act.type = StrategyActionType::Close;
        act.dir = pos_dir;
        act.ts = ts;
        act.price = price;
        clear_position();
        return act;
    }

    if (pos_dir == -1 && ret >= sl_bp) {
        act.type = StrategyActionType::Close;
        act.dir = pos_dir;
        act.ts = ts;
        act.price = price;
        clear_position();
        return act;
    }

    if (ts - entry_ts >= hold_sec) {
        act.type = StrategyActionType::Close;
        act.dir = pos_dir;
        act.ts = ts;
        act.price = price;
        clear_position();
        return act;
    }

    return act;
}

void MeanReversionStrategy::clear_position() {
    in_position = false;
    pos_dir = 0;
    entry_price = 0.0;
    entry_ts = 0.0;
}
