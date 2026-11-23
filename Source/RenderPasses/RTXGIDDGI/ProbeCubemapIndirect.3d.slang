#include "RTXGIConfig.slang"
#include "ProbeCubemapCommon.slang"
#include "RTXGI/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl"
import Scene.Raster;
#ifndef PROBE_MULTIVIEW
#define PROBE_MULTIVIEW 0
#endif
#if PROBE_MULTIVIEW
// Native PSO dispatcher recognizes this reflected parameter block as an
// explicit request for a three-view pipeline. It must remain live in the VS.
struct ViewInstancingSettings
{
    uint viewCount;
};
#if PROBE_MULTIVIEW_ACROSS_PROBES
ParameterBlock<ViewInstancingSettings> gFalcorViewInstancing3AcrossProbes;
#define captureViewSettings gFalcorViewInstancing3AcrossProbes
#else
ParameterBlock<ViewInstancingSettings> gFalcorViewInstancing3;
#define captureViewSettings gFalcorViewInstancing3
#endif
StructuredBuffer<uint> gViewMasks;
#endif
StructuredBuffer<DDGIVolumeDescGPUPacked> DDGIVolumes;
Texture2DArray<float4> gProbeData;
cbuffer CaptureCB
{
    uint gStart;
    uint gCount;
    uint gTotal;
    float gNear;
    float gFar;
}
#if PROBE_CAPTURE_DIAGNOSTICS
cbuffer CaptureDiagnosticCB { uint gDiagnosticMode; }
#else
static const uint gDiagnosticMode = 0;
#endif
struct VIn
{
#if PROBE_CAPTURE_NO_VERTEX_POSITION
    uint vertexID : SV_VertexID;
#else
    float3 pos : POSITION;
#endif
    uint encoded : DRAW_ID;
};
struct VOut
{
    float4 h : SV_Position;
    nointerpolation uint inst : TEXCOORD1;
    uint layer : SV_RenderTargetArrayIndex;
};
VOut vsMain(VIn i
#if PROBE_MULTIVIEW && !PROBE_CAPTURE_INDEPENDENT_VIEW
            ,
            uint viewID : SV_ViewID
#endif
)
{
    VOut o;
#if PROBE_MULTIVIEW && PROBE_CAPTURE_INDEPENDENT_VIEW
    uint viewID = 0;
#endif
    uint inst = i.encoded / 192, view = i.encoded % 192;
#if PROBE_MULTIVIEW
#if PROBE_MULTIVIEW_ACROSS_PROBES
    uint slot = (view / 6) * 3 + min(viewID, captureViewSettings.viewCount - 1), face = view % 6;
#else
    uint slot = view / 2, face = (view % 2) * 3 + min(viewID, captureViewSettings.viewCount - 1);
#endif
    uint mask = gViewMasks[i.encoded];
#else
    uint slot = view / 6, face = view % 6;
#endif
    o.inst = inst;
#if PROBE_MULTIVIEW
    // The PSO adds each view's static layer offset. Keep this VS output view-independent.
#if PROBE_MULTIVIEW_ACROSS_PROBES
    o.layer = (view / 6) * 18 + view % 6;
#else
    o.layer = (view / 2) * 6 + (view % 2) * 3;
#endif
#else
    o.layer = view;
#endif
#if PROBE_CAPTURE_NO_VERTEX_POSITION
    float3 inputPosition = float3(float(i.vertexID & 1023u), float((i.vertexID >> 10) & 1023u), 0);
#else
    float3 inputPosition = i.pos;
#endif
    if (gDiagnosticMode == 3 || gDiagnosticMode == 4) { o.h = float4(inputPosition.xy, -1 - float(gDiagnosticMode & 4), 1); return o; }
    GeometryInstanceID id = {inst};
    float3 pos = mul(gScene.getWorldMatrix(id), float4(inputPosition, 1)).xyz;
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    float3 origin = DDGIGetProbeWorldPosition(DDGIGetProbeCoords((gStart + slot) % gTotal, volume), volume, gProbeData);
    float3 F = cubeForward(face), U = cubeUp(face), R = cross(F, U);
#if PROBE_MULTIVIEW && PROBE_MULTIVIEW_ACROSS_PROBES
    float3 base = float3(dot(pos, R), dot(pos, U), dot(pos, F));
    float3 projected = base - float3(dot(origin, R), dot(origin, U), dot(origin, F));
#else
    float3 p = pos - origin;
    float3 projected = float3(dot(p, R), dot(p, U), dot(p, F));
#endif
    float z = projected.z;
    // Reversed-Z: depth = 1 at gNear, 0 at gFar. Keeps float precision at distance.
    o.h = float4(projected.xy, gNear * (gFar - z) / (gFar - gNear), z);
#if PROBE_MULTIVIEW
    // Preserve per-face culling when a draw broadcasts to three views.
    if ((mask & (1u << viewID)) == 0)
        o.h = float4(0, 0, -1, 1);
#endif
    if (gDiagnosticMode == 2) o.h.z = -abs(o.h.w) - 1;
    if (gDiagnosticMode == 5)
    {
#if PROBE_MULTIVIEW
        o.h.z = -abs(o.h.w) - float(captureViewSettings.viewCount);
#else
        o.h.z = -abs(o.h.w) - 3;
#endif
    }
    return o;
}
uint4 psMain(VOut i, uint prim : SV_PrimitiveID, float3 bary : SV_Barycentrics) : SV_Target0
{
    if (gDiagnosticMode == 1) return uint4(i.inst, prim, 0, 0);
    GeometryInstanceID id = {i.inst};
    TriangleHit hit;
    hit.instanceID = id;
    hit.primitiveIndex = prim;
    hit.barycentrics = bary.yz;
    // Only alpha-masked materials need interpolated vertex data.
    uint materialID = gScene.getMaterialID(id);
    if (gScene.materials.getMaterialHeader(materialID).getAlphaMode() == AlphaMode::Mask)
    {
        VertexData v = gScene.getVertexData(hit);
        if (gScene.materials.alphaTest(v, materialID, 0.f))
            discard;
    }
    PackedHitInfo packed = hit.pack();
#if HIT_INFO_USE_COMPRESSION
    return uint4(packed, 0, 0);
#else
    return packed;
#endif
}
