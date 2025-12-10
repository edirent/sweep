#pragma once
#include <deque>
#include <map>
#include <vector>
#include <utility>
#include <cstdint>

#include "sweep_model.h"  // for Side enum

// 方向标记
enum class AggRunDir : int8_t { None = 0, Buy = 1, Sell = -1 };
enum class WeakSide : int8_t { None = 0, Bid = 1, Ask = -1 };

struct OrderFlowFrame {
    double ts = 0.0;
    double mid = 0.0;
    double best_bid = 0.0;
    double best_ask = 0.0;

    double buy_vol_1s = 0.0;
    double sell_vol_1s = 0.0;
    double buy_vol_3s = 0.0;
    double sell_vol_3s = 0.0;
    double buy_vol_10s = 0.0;
    double sell_vol_10s = 0.0;

    double buy_share_1s = 0.0;
    double sell_share_1s = 0.0;
    double buy_share_3s = 0.0;
    double sell_share_3s = 0.0;
    double buy_share_10s = 0.0;
    double sell_share_10s = 0.0;

    double liq01_bid = 0.0;
    double liq01_ask = 0.0;
    double liq03_bid = 0.0;
    double liq03_ask = 0.0;
    double liq05_bid = 0.0;
    double liq05_ask = 0.0;

    bool is_new_high_20s = false;
    bool is_new_low_20s = false;
    bool is_new_high_30s = false;
    bool is_new_low_30s = false;

    AggRunDir agg_run_dir = AggRunDir::None;
    WeakSide weak_side_01 = WeakSide::None;
};

// 滑窗极值（高/低）维护：O(1) 入队 / 过期 / 查询
class RollingExtreme {
public:
    explicit RollingExtreme(double window_sec)
        : window_sec_(window_sec) {}

    void add(double ts, double value) {
        // 维护 max
        while (!max_q_.empty() && max_q_.back().second <= value) {
            max_q_.pop_back();
        }
        max_q_.emplace_back(ts, value);

        // 维护 min
        while (!min_q_.empty() && min_q_.back().second >= value) {
            min_q_.pop_back();
        }
        min_q_.emplace_back(ts, value);

        evict(ts);
    }

    void evict(double ts_now) {
        while (!max_q_.empty() && ts_now - max_q_.front().first > window_sec_) {
            max_q_.pop_front();
        }
        while (!min_q_.empty() && ts_now - min_q_.front().first > window_sec_) {
            min_q_.pop_front();
        }
    }

    bool empty() const { return max_q_.empty() || min_q_.empty(); }
    double current_max() const { return max_q_.empty() ? 0.0 : max_q_.front().second; }
    double current_min() const { return min_q_.empty() ? 0.0 : min_q_.front().second; }

private:
    double window_sec_;
    std::deque<std::pair<double, double>> max_q_;
    std::deque<std::pair<double, double>> min_q_;
};

class OrderFlowFeatureExtractor {
public:
    OrderFlowFeatureExtractor();

    // trades: ts 秒, price, volume, side
    void add_trade(double ts, double price, double volume, Side side);

    // L2 book updates：传入 price,size 列表（size<=0 表示删除）
    void apply_l2_snapshot(const std::vector<std::pair<double, double>>& bids,
                           const std::vector<std::pair<double, double>>& asks);
    void apply_l2_delta(const std::vector<std::pair<double, double>>& bids,
                        const std::vector<std::pair<double, double>>& asks);

    // 组合一帧特征；ts_now 用 last_tick_ts_ 兜底
    OrderFlowFrame get_frame(double ts_now = 0.0);

private:
    struct TradePoint {
        double ts;
        double volume;
        Side side;
    };

    struct AggBucket {
        int sec;       // floor(ts)
        double buy;
        double sell;
    };

    std::deque<TradePoint> trades_;   // 保存 <=10s 的 trade
    std::deque<AggBucket> buckets_;   // 最近 5 个 1s 桶

    double last_price_ = 0.0;
    double last_tick_ts_ = 0.0;

    std::map<double, double> bids_;   // price -> size
    std::map<double, double> asks_;

    RollingExtreme highlow_20s_;
    RollingExtreme highlow_30s_;

    AggRunDir agg_run_dir_ = AggRunDir::None;

    void prune_trades(double ts_now);
    void update_bucket(double ts, double volume, Side side);
    void refresh_agg_run();
    double best_bid() const;
    double best_ask() const;
    void apply_book_entries(const std::vector<std::pair<double, double>>& bids,
                            const std::vector<std::pair<double, double>>& asks,
                            bool snapshot);
    std::pair<double, double> depth_within(double mid, double pct) const;
};
