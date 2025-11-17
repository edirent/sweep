cmake_minimum_required(VERSION 3.14)
project(sweep_core)

set(CMAKE_CXX_STANDARD 17)

find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
find_package(pybind11 CONFIG REQUIRED)

# 编译你的 cpp 代码
pybind11_add_module(sweep_core
    cpp/bindings.cpp
    cpp/sweep_model.cpp
)

# Python 模块名： sweep_core
# 输出文件会是 sweep_core.cpython-*.so
