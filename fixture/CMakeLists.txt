# forgefixture: the ForgeFIRM bench actuator (ESP32-S3, ESP-IDF).
# The wifi details and the API key come from fixture.env next to this
# file (see main/CMakeLists.txt and README.md); nothing else is needed.
cmake_minimum_required(VERSION 3.16)

set(SDKCONFIG_DEFAULTS "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.defaults")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(forgefixture)
