add_plugin(TraditionalProbeGI)
target_sources(TraditionalProbeGI PRIVATE
    TraditionalProbeGI.h
    TraditionalProbeGI.cpp
    TraditionalProbeGI.rt.slang
    ProbeSH.slang
)
target_copy_shaders(TraditionalProbeGI RenderPasses/TraditionalProbeGI)
target_source_group(TraditionalProbeGI "RenderPasses")
