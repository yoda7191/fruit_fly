cmake_minimum_required(VERSION 3.18)
project(fruit_fly LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)   # the simulation is ~10x faster than Debug
endif()

option(FRUIT_FLY_BUILD_CLI    "Build the fruit_fly command-line tool" ON)
option(FRUIT_FLY_BUILD_TESTS  "Build the tests" ON)
option(FRUIT_FLY_BUILD_PYTHON "Build the fruit_fly_core Python module" OFF)

# ---- core library (shared by the CLI, the tests and the Python module)
add_library(fruit_fly_lib STATIC
  core/src/csv.cpp
  core/src/network.cpp
  core/src/simulator.cpp
  core/src/odours.cpp
  core/src/experiment.cpp
  core/src/analysis.cpp)
target_include_directories(fruit_fly_lib PUBLIC core/include)
set_target_properties(fruit_fly_lib PROPERTIES POSITION_INDEPENDENT_CODE ON)
if(MSVC)
  target_compile_options(fruit_fly_lib PRIVATE /W4)
else()
  target_compile_options(fruit_fly_lib PRIVATE -Wall -Wextra)
endif()

# ---- command-line tool
if(FRUIT_FLY_BUILD_CLI)
  add_executable(fruit_fly core/apps/fruit_fly_cli.cpp)
  target_link_libraries(fruit_fly PRIVATE fruit_fly_lib)
endif()

# ---- tests:  ctest --test-dir build --output-on-failure
if(FRUIT_FLY_BUILD_TESTS)
  enable_testing()
  add_executable(test_unit tests/test_unit.cpp)
  target_link_libraries(test_unit PRIVATE fruit_fly_lib)
  add_test(NAME unit COMMAND test_unit)

  add_executable(test_integration tests/test_integration.cpp)
  target_link_libraries(test_integration PRIVATE fruit_fly_lib)
  add_test(NAME integration
           COMMAND test_integration ${CMAKE_SOURCE_DIR}/data/synthetic
                                    ${CMAKE_SOURCE_DIR}/data/raw/door)
  set_tests_properties(integration PROPERTIES SKIP_RETURN_CODE 77)
endif()

# ---- Python module
if(FRUIT_FLY_BUILD_PYTHON)
  find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(fruit_fly_core core/python/bindings.cpp)
  target_link_libraries(fruit_fly_core PRIVATE fruit_fly_lib)
  install(TARGETS fruit_fly_core LIBRARY DESTINATION .)
endif()
