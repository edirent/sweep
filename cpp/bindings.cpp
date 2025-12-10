// cpp/bindings.cpp
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "sweep_model.h"
#include "mean_reversion_strategy.h"
#include "orderflow_features.h"

namespace py = pybind11;

PYBIND11_MODULE(sweep_core, m) {
    // --- 基础枚举 ---

    py::enum_<Side>(m, "Side")
        .value("Buy",  Side::Buy)
        .value("Sell", Side::Sell);

    py::enum_<SweepSignal>(m, "SweepSignal")
        .value("NoSignal", SweepSignal::NoSignal)
        .value("UpSweep",  SweepSignal::UpSweep)
        .value("DownSweep",SweepSignal::DownSweep);

    // --- Tick 结构 ---

    py::class_<Tick>(m, "Tick")
        .def(py::init<>())
        .def_readwrite("timestamp", &Tick::timestamp)
        .def_readwrite("price",     &Tick::price)
        .def_readwrite("volume",    &Tick::volume)
        .def_readwrite("side",      &Tick::side);

    // --- C++ sweep 聚合后的事件（用于 offline / 策略） ---

    py::class_<SweepEventMeta>(m, "SweepEventMeta")
        .def_readonly("ts_start",    &SweepEventMeta::ts_start)
        .def_readonly("ts_end",      &SweepEventMeta::ts_end)
        .def_readonly("direction",   &SweepEventMeta::direction)
        .def_readonly("price_start", &SweepEventMeta::price_start)
        .def_readonly("price_end",   &SweepEventMeta::price_end)
        .def_readonly("volume_total",&SweepEventMeta::volume_total);

    // --- SweepModel 本体 ---

    py::class_<SweepModel>(m, "SweepModel")
        .def(py::init<double,double,double>(),
             py::arg("short_window_sec") = 0.3,
             py::arg("long_window_sec")  = 10.0,
             py::arg("threshold_ratio")  = 3.0)
        .def("process_tick", &SweepModel::process_tick)
        .def("get_last_event", &SweepModel::get_last_event);

    // --- 策略动作枚举 & 结构 ---

    py::enum_<StrategyActionType>(m, "StrategyActionType")
        .value("Idle",      StrategyActionType::Idle)
        .value("OpenLong",  StrategyActionType::OpenLong)
        .value("OpenShort", StrategyActionType::OpenShort)
        .value("Close",     StrategyActionType::Close);

    py::class_<StrategyAction>(m, "StrategyAction")
        .def(py::init<>())
        .def_readwrite("type",  &StrategyAction::type)
        .def_readwrite("dir",   &StrategyAction::dir)
        .def_readwrite("price", &StrategyAction::price)
        .def_readwrite("ts",    &StrategyAction::ts);

    // --- 反 sweep 均值回归策略 ---

    py::class_<MeanReversionStrategy>(m, "MeanReversionStrategy")
        .def(py::init<double,double,double,double>(),
             py::arg("delay_ms") = 80.0,
             py::arg("hold_sec") = 5.0,
             py::arg("tp_bp")    = 2.0,
             py::arg("sl_bp")    = 2.0)
        .def("on_sweep", &MeanReversionStrategy::on_sweep)
        .def("on_tick",  &MeanReversionStrategy::on_tick);

    // --- Orderflow frame & extractor ---
    py::enum_<AggRunDir>(m, "AggRunDir")
        .value("None", AggRunDir::None)
        .value("Buy",  AggRunDir::Buy)
        .value("Sell", AggRunDir::Sell);

    py::enum_<WeakSide>(m, "WeakSide")
        .value("None", WeakSide::None)
        .value("Bid",  WeakSide::Bid)
        .value("Ask",  WeakSide::Ask);

    py::class_<OrderFlowFrame>(m, "OrderFlowFrame")
        .def_readonly("ts", &OrderFlowFrame::ts)
        .def_readonly("mid", &OrderFlowFrame::mid)
        .def_readonly("best_bid", &OrderFlowFrame::best_bid)
        .def_readonly("best_ask", &OrderFlowFrame::best_ask)
        .def_readonly("buy_vol_1s", &OrderFlowFrame::buy_vol_1s)
        .def_readonly("sell_vol_1s", &OrderFlowFrame::sell_vol_1s)
        .def_readonly("buy_vol_3s", &OrderFlowFrame::buy_vol_3s)
        .def_readonly("sell_vol_3s", &OrderFlowFrame::sell_vol_3s)
        .def_readonly("buy_vol_10s", &OrderFlowFrame::buy_vol_10s)
        .def_readonly("sell_vol_10s", &OrderFlowFrame::sell_vol_10s)
        .def_readonly("buy_share_1s", &OrderFlowFrame::buy_share_1s)
        .def_readonly("sell_share_1s", &OrderFlowFrame::sell_share_1s)
        .def_readonly("buy_share_3s", &OrderFlowFrame::buy_share_3s)
        .def_readonly("sell_share_3s", &OrderFlowFrame::sell_share_3s)
        .def_readonly("buy_share_10s", &OrderFlowFrame::buy_share_10s)
        .def_readonly("sell_share_10s", &OrderFlowFrame::sell_share_10s)
        .def_readonly("liq01_bid", &OrderFlowFrame::liq01_bid)
        .def_readonly("liq01_ask", &OrderFlowFrame::liq01_ask)
        .def_readonly("liq03_bid", &OrderFlowFrame::liq03_bid)
        .def_readonly("liq03_ask", &OrderFlowFrame::liq03_ask)
        .def_readonly("liq05_bid", &OrderFlowFrame::liq05_bid)
        .def_readonly("liq05_ask", &OrderFlowFrame::liq05_ask)
        .def_readonly("is_new_high_20s", &OrderFlowFrame::is_new_high_20s)
        .def_readonly("is_new_low_20s", &OrderFlowFrame::is_new_low_20s)
        .def_readonly("is_new_high_30s", &OrderFlowFrame::is_new_high_30s)
        .def_readonly("is_new_low_30s", &OrderFlowFrame::is_new_low_30s)
        .def_readonly("agg_run_dir", &OrderFlowFrame::agg_run_dir)
        .def_readonly("weak_side_01", &OrderFlowFrame::weak_side_01);

    py::class_<OrderFlowFeatureExtractor>(m, "OrderFlowFeatureExtractor")
        .def(py::init<>())
        .def("add_trade", &OrderFlowFeatureExtractor::add_trade,
             py::arg("ts"), py::arg("price"), py::arg("volume"), py::arg("side"))
        .def("apply_l2_snapshot", &OrderFlowFeatureExtractor::apply_l2_snapshot,
             py::arg("bids"), py::arg("asks"))
        .def("apply_l2_delta", &OrderFlowFeatureExtractor::apply_l2_delta,
             py::arg("bids"), py::arg("asks"))
        .def("get_frame", &OrderFlowFeatureExtractor::get_frame,
             py::arg("ts_now") = 0.0);
}
