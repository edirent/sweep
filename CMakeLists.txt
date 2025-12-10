
cmake_minimum_required(VERSION 3.14)
project(sweep_core LANGUAGES CXX)

# C++ 标准
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# 找 Python / pybind11
find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
find_package(pybind11 CONFIG REQUIRED)

# 如果你希望开一点优化，可以顺手加（可选）
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# 编译 Python 模块 sweep_core
pybind11_add_module(sweep_core
    cpp/bindings.cpp
    cpp/sweep_model.cpp
    cpp/mean_reversion_strategy.cpp
    cpp/orderflow_features.cpp
)

# 包含头文件目录（sweep_model.h / mean_reversion_strategy.h 在 cpp/ 目录）
target_include_directories(sweep_core
    PRIVATE
        ${Python3_INCLUDE_DIRS}
        cpp
)

# 可选：如果你想强制开一点优化（按需留着）
# target_compile_options(sweep_core PRIVATE -O3 -Wall -Wextra)
