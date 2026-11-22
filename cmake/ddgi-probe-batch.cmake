# Generate small, auditable adaptations of NVIDIA SDK kernels in the build tree.
# Keep the downloaded SDK intact. All threads of a blending group address the
# same probe, so the batch gate precedes shared-memory loads and barriers.
foreach(kind Blending Relocation Classification)
    set(source "${SDK}/rtxgi-sdk/shaders/ddgi/Probe${kind}CS.hlsl")
    file(READ "${source}" code)
    if(kind STREQUAL "Blending")
        set(anchor "int probeIndex = DDGIGetProbeIndex(DispatchThreadID, RTXGI_DDGI_PROBE_NUM_TEXELS, volume);")
    else()
        set(anchor "uint probeIndex = DispatchThreadID.x;")
    endif()
    string(FIND "${code}" "${anchor}" found)
    if(found EQUAL -1)
        message(FATAL_ERROR "NVIDIA DDGI ${kind} batch insertion point changed; review the SDK update.")
    endif()
    string(REPLACE "${anchor}" "${anchor}\n    if ((uint(probeIndex) + gBatchTotal - gBatchStart) % gBatchTotal >= gBatchCount) return;" code "${code}")
    file(WRITE "${OUTPUT}/BatchProbe${kind}CS.hlsl"
        "// Generated from NVIDIA RTXGI-DDGI; retain the upstream license below.\ncbuffer ProbeBatchCB { uint gBatchStart; uint gBatchCount; uint gBatchTotal; }\n${code}")
endforeach()
