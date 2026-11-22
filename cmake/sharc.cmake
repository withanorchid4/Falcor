include_guard(GLOBAL)
include(FetchContent)
if(POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)
endif()
# Official SHaRC 1.8.3, pinned so new machines build identical shader code.
FetchContent_Declare(sharc
    URL https://codeload.github.com/NVIDIA-RTX/SHARC/zip/4e21b585c33c83d723ca9a1e11bbb1090d145793
    URL_HASH SHA256=2fce446623df71f6cb6217da300422a0b4cfb7d7dca92d8111708dc030d60b4c
    SOURCE_SUBDIR _falcor_shader_only
)
FetchContent_MakeAvailable(sharc)
set(FALCOR_SHARC_DIR "${sharc_SOURCE_DIR}")
