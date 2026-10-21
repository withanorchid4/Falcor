include_guard(GLOBAL)
include(FetchContent)
if(POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)
endif()

# RTXGI-DDGI v1.3.7. Keep the separately licensed SDK outside the source tree;
# FetchContent caches it in the ignored build directory. SOURCE_SUBDIR prevents
# configuring the upstream native D3D12/Vulkan SDK and its test harness: this
# integration uses its original shader kernels through Falcor's GPU abstraction.
FetchContent_Declare(rtxgi_ddgi
    URL https://codeload.github.com/NVIDIAGameWorks/RTXGI-DDGI/zip/c233266e95931231961f35c842c78e7c4bdc50cf
    URL_HASH SHA256=141df8a44aa24dfe79782fa45c11cd112c9a6726105d388ce0696a0a68974108
    SOURCE_SUBDIR _falcor_shader_only
)
FetchContent_MakeAvailable(rtxgi_ddgi)

set(FALCOR_RTXGI_DDGI_DIR "${rtxgi_ddgi_SOURCE_DIR}")
