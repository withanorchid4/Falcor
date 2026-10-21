add_plugin(TraditionalProbeGI)
target_sources(TraditionalProbeGI PRIVATE
    WickedProbeVisibility.h
    WickedProbeVisibility.cpp
    WickedProbeVisibility.slang
    WickedProbeBlend.cs.slang
    TraditionalProbeGI.h
    TraditionalProbeGI.cpp
    TraditionalProbeGI.rt.slang
    ProbeSH.slang
    ProbeSparse.slang
    ProbeSurface.slang
    ProbeSparseResolve.cs.slang
    ProbeDistance.slang
    ProbeDistanceBlend.cs.slang
    ProbeDebug.3d.slang
)
target_copy_shaders(TraditionalProbeGI RenderPasses/TraditionalProbeGI)
target_source_group(TraditionalProbeGI "RenderPasses")

add_custom_command(TARGET TraditionalProbeGI POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_CURRENT_SOURCE_DIR}/WickedEngine-LICENSE.txt
        $<TARGET_FILE_DIR:TraditionalProbeGI>/WickedEngine-LICENSE.txt
)
