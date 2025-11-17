// cpp/bindings.cpp
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "sweep_model.h"

namespace py = pybind11;

PYBIND11_MODULE(sweep_core, m) {
    py::enum_<Side>(m, "Side")
        .value("Buy", Side::Buy)
        .value("Sell", Side::Sell);

    py::enum_<SweepSignal>(m, "SweepSignal")
        .value("NoSignal", SweepSignal::NoSignal)
        .value("UpSweep", SweepSignal::UpSweep)
        .value("DownSweep", SweepSignal::DownSweep);


    py::class_<Tick>(m, "Tick")
        .def(py::init<>())
        .def_readwrite("timestamp", &Tick::timestamp)
        .def_readwrite("price", &Tick::price)
        .def_readwrite("volume", &Tick::volume)
        .def_readwrite("side", &Tick::side);

    py::class_<SweepModel>(m, "SweepModel")
        .def(py::init<double,double,double>(),
             py::arg("short_window_sec") = 2.0,
             py::arg("long_window_sec")  = 20.0,
             py::arg("threshold_ratio")  = 3.0)
        .def("process_tick", &SweepModel::process_tick);
}
