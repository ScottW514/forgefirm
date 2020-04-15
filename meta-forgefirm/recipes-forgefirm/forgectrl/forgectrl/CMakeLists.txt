cmake_minimum_required(VERSION 3.10)
project(forgectrl C)

set(CMAKE_C_STANDARD 11)
file(GLOB sources "${PROJECT_SOURCE_DIR}/*.c")

add_executable(forgectrl ${sources})
install(TARGETS forgectrl RUNTIME DESTINATION bin)
