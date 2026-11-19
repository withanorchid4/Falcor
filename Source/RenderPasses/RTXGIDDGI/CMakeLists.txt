include(${PROJECT_SOURCE_DIR}/cmake/rtxgi-ddgi.cmake)

add_plugin(RTXGIDDGI)
target_sources(RTXGIDDGI PRIVATE
    LumenWorldCache.cpp
    LumenWorldCache.slang
    LumenWorldCache.cs.slang
    LumenWorldCacheTrace.slang
    RTXGIDDGI.h
    RTXGIDDGI.cpp
    ProbeVisualization.cpp
    ProbeVisualization.cs.slang
    DDGIReconstruct.cpp
    DDGIReconstruct.h
    DDGIReconstruct.cs.slang
    ReSTIRGather.slang
    RTXGIDDGI.rt.slang
    WorldRadianceCache.rt.slang
    WorldRadianceCache.slang
    WorldRadianceCacheStress.slang
    WorldRadianceCache.cs.slang
    WorldRadianceCacheDebug.slang
    RTXGIConfig.slang
    ProbeBlending.cs.slang
    ProbeRelocation.cs.slang
    ProbeClassification.cs.slang
    SanitizeEnvironment.cs.slang
)
target_include_directories(RTXGIDDGI PRIVATE ${FALCOR_RTXGI_DDGI_DIR}/rtxgi-sdk/include)
target_compile_definitions(RTXGIDDGI PRIVATE RTXGI_COORDINATE_SYSTEM=2 RTXGI_DDGI_RESOURCE_MANAGEMENT=0)
target_copy_shaders(RTXGIDDGI RenderPasses/RTXGIDDGI)
target_source_group(RTXGIDDGI "RenderPasses")
target_sources(RTXGIDDGI PRIVATE ${FALCOR_RTXGI_DDGI_DIR}/rtxgi-sdk/src/Math.cpp)

# Preserve the SDK's directory layout: its HLSL includes shared C++/HLSL headers
# through relative paths. Do not rewrite or vendor the third-party sources.
add_custom_target(RTXGIDDGIShaders
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${FALCOR_RTXGI_DDGI_DIR}/rtxgi-sdk/shaders"
        "${FALCOR_SHADER_OUTPUT_DIRECTORY}/RTXGI/rtxgi-sdk/shaders"
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${FALCOR_RTXGI_DDGI_DIR}/rtxgi-sdk/include"
        "${FALCOR_SHADER_OUTPUT_DIRECTORY}/RTXGI/rtxgi-sdk/include"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${FALCOR_RTXGI_DDGI_DIR}/License.txt"
        "${FALCOR_SHADER_OUTPUT_DIRECTORY}/RTXGI/License.txt"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${FALCOR_RTXGI_DDGI_DIR}/License.txt"
        "${FALCOR_OUTPUT_DIRECTORY}/RTXGI-DDGI-License.txt"
    COMMENT "Deploying NVIDIA RTXGI-DDGI shaders and license"
    VERBATIM
)
set_target_properties(RTXGIDDGIShaders PROPERTIES FOLDER "Misc")
add_dependencies(RTXGIDDGI RTXGIDDGIShaders)
