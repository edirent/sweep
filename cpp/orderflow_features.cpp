#include "orderflow_features.h"
#include <algorithm>
#include <cmath>

OrderFlowFeatureExtractor::OrderFlowFeatureExtractor()
    : highlow_20s_(20.0), highlow_30s_(30.0) {}

void OrderFlowFeatureExtractor::prune_trades(double ts_now) {
    double cutoff = ts_now - 10.0;  // longest window
    while (!trades_.empty() && trades_.front().ts < cutoff) {
        trades_.pop_front();
    }
    int cutoff_sec = static_cast<int>(std::floor(ts_now)) - 5;
    while (!buckets_.empty() && buckets_.front().sec < cutoff_sec) {
        buckets_.pop_front();
    }
}

void OrderFlowFeatureExtractor::update_bucket(double ts, double volume, Side side) {
    int sec = static_cast<int>(std::floor(ts));
    if (buckets_.empty() || buckets_.back().sec != sec) {
        buckets_.push_back({sec, 0.0, 0.0});
    }
    AggBucket& bk = buckets_.back();
    if (side == Side::Buy) {
        bk.buy += volume;
    } else {
        bk.sell += volume;
    }
    int cutoff_sec = sec - 5;
    while (!buckets_.empty() && buckets_.front().sec < cutoff_sec) {
        buckets_.pop_front();
    }
}

void OrderFlowFeatureExtractor::refresh_agg_run() {
    agg_run_dir_ = AggRunDir::None;
    if (buckets_.size() < 3) return;

    // 取最近 3 个桶判断方向一致且净流增强
    auto it = buckets_.rbegin();
    AggBucket b3 = *it++;  // latest
    AggBucket b2 = *it++;
    AggBucket b1 = *it;

    auto bucket_dir = [](const AggBucket& b) -> AggRunDir {
        double net = b.buy - b.sell;
        double tot = b.buy + b.sell;
        if (tot <= 0.0) return AggRunDir::None;
        double share = b.buy / tot;
        if (net > 0 && share >= 0.7) return AggRunDir::Buy;
        if (net < 0 && share <= 0.3) return AggRunDir::Sell;
        return AggRunDir::None;
    };

    AggRunDir d1 = bucket_dir(b1);
    AggRunDir d2 = bucket_dir(b2);
    AggRunDir d3 = bucket_dir(b3);
    if (d1 == AggRunDir::None || d2 == AggRunDir::None || d3 == AggRunDir::None) return;
    if (!(d1 == d2 && d2 == d3)) return;

    auto net_abs = [](const AggBucket& b) { return std::fabs(b.buy - b.sell); };
    double n1 = net_abs(b1);
    double n2 = net_abs(b2);
    double n3 = net_abs(b3);
    if (n1 <= n2 && n2 <= n3) {
        agg_run_dir_ = d3;
    }
}

double OrderFlowFeatureExtractor::best_bid() const {
    if (bids_.empty()) return 0.0;
    return bids_.rbegin()->first;  // max key
}

double OrderFlowFeatureExtractor::best_ask() const {
    if (asks_.empty()) return 0.0;
    return asks_.begin()->first;   // min key
}

void OrderFlowFeatureExtractor::apply_book_entries(
    const std::vector<std::pair<double, double>>& bids,
    const std::vector<std::pair<double, double>>& asks,
    bool snapshot) {

    if (snapshot) {
        bids_.clear();
        asks_.clear();
    }
    for (const auto& kv : bids) {
        double px = kv.first;
        double sz = kv.second;
        if (sz <= 0.0) {
            bids_.erase(px);
        } else {
            bids_[px] = sz;
        }
    }
    for (const auto& kv : asks) {
        double px = kv.first;
        double sz = kv.second;
        if (sz <= 0.0) {
            asks_.erase(px);
        } else {
            asks_[px] = sz;
        }
    }
}

std::pair<double, double> OrderFlowFeatureExtractor::depth_within(double mid, double pct) const {
    double lower = mid * (1.0 - pct);
    double upper = mid * (1.0 + pct);
    double bid_depth = 0.0;
    double ask_depth = 0.0;
    for (auto it = bids_.lower_bound(lower); it != bids_.end(); ++it) {
        bid_depth += it->second;
    }
    for (auto it = asks_.begin(); it != asks_.end() && it->first <= upper; ++it) {
        if (it->first < upper) ask_depth += it->second;
        else break;
    }
    return {bid_depth, ask_depth};
}

void OrderFlowFeatureExtractor::add_trade(double ts, double price, double volume, Side side) {
    last_price_ = price;
    last_tick_ts_ = ts;
    trades_.push_back({ts, volume, side});
    prune_trades(ts);
    update_bucket(ts, volume, side);
    refresh_agg_run();
}

void OrderFlowFeatureExtractor::apply_l2_snapshot(
    const std::vector<std::pair<double, double>>& bids,
    const std::vector<std::pair<double, double>>& asks) {
    apply_book_entries(bids, asks, true);
}

void OrderFlowFeatureExtractor::apply_l2_delta(
    const std::vector<std::pair<double, double>>& bids,
    const std::vector<std::pair<double, double>>& asks) {
    apply_book_entries(bids, asks, false);
}

OrderFlowFrame OrderFlowFeatureExtractor::get_frame(double ts_now) {
    OrderFlowFrame f;
    if (ts_now <= 0.0) ts_now = last_tick_ts_;
    f.ts = ts_now;

    prune_trades(ts_now);
    refresh_agg_run();

    double buy1 = 0.0, sell1 = 0.0, buy3 = 0.0, sell3 = 0.0, buy10 = 0.0, sell10 = 0.0;
    for (const auto& t : trades_) {
        double age = ts_now - t.ts;
        if (age < 0.0) continue;
        if (age <= 10.0) {
            if (t.side == Side::Buy) buy10 += t.volume;
            else sell10 += t.volume;
            if (age <= 3.0) {
                if (t.side == Side::Buy) buy3 += t.volume;
                else sell3 += t.volume;
            }
            if (age <= 1.0) {
                if (t.side == Side::Buy) buy1 += t.volume;
                else sell1 += t.volume;
            }
        }
    }

    auto share = [](double b, double s) -> std::pair<double, double> {
        double tot = b + s;
        if (tot <= 0.0) return {0.0, 0.0};
        double buy_share = b / tot;
        return {buy_share, 1.0 - buy_share};
    };

    f.buy_vol_1s = buy1; f.sell_vol_1s = sell1;
    f.buy_vol_3s = buy3; f.sell_vol_3s = sell3;
    f.buy_vol_10s = buy10; f.sell_vol_10s = sell10;

    auto s1 = share(buy1, sell1);
    auto s3 = share(buy3, sell3);
    auto s10 = share(buy10, sell10);
    f.buy_share_1s = s1.first; f.sell_share_1s = s1.second;
    f.buy_share_3s = s3.first; f.sell_share_3s = s3.second;
    f.buy_share_10s = s10.first; f.sell_share_10s = s10.second;

    f.best_bid = best_bid();
    f.best_ask = best_ask();
    if (f.best_bid > 0.0 && f.best_ask > 0.0) {
        f.mid = 0.5 * (f.best_bid + f.best_ask);
    } else {
        f.mid = last_price_;
    }

    if (f.mid > 0.0) {
        auto d01 = depth_within(f.mid, 0.001);
        auto d03 = depth_within(f.mid, 0.003);
        auto d05 = depth_within(f.mid, 0.005);
        f.liq01_bid = d01.first; f.liq01_ask = d01.second;
        f.liq03_bid = d03.first; f.liq03_ask = d03.second;
        f.liq05_bid = d05.first; f.liq05_ask = d05.second;
    }

    // 弱侧检测：0.1% 档
    if (f.liq01_bid > 0.0 && f.liq01_ask > 0.0) {
        if (f.liq01_bid < 0.4 * f.liq01_ask) {
            f.weak_side_01 = WeakSide::Bid;
        } else if (f.liq01_ask < 0.4 * f.liq01_bid) {
            f.weak_side_01 = WeakSide::Ask;
        }
    }

    // 高低点检测
    if (f.mid > 0.0) {
        highlow_20s_.add(ts_now, f.mid);
        highlow_30s_.add(ts_now, f.mid);
        f.is_new_high_20s = (!highlow_20s_.empty() && f.mid >= highlow_20s_.current_max());
        f.is_new_low_20s  = (!highlow_20s_.empty() && f.mid <= highlow_20s_.current_min());
        f.is_new_high_30s = (!highlow_30s_.empty() && f.mid >= highlow_30s_.current_max());
        f.is_new_low_30s  = (!highlow_30s_.empty() && f.mid <= highlow_30s_.current_min());
    }

    f.agg_run_dir = agg_run_dir_;
    return f;
}
