// Independent probe visualization. Hardware BVH traversal replaces the former
// screen-pixel x probe-count loop. Unit-sphere intersection is analytic.
#include "RTXGIConfig.slang"
#include "RTXGI/rtxgi-sdk/shaders/ddgi/include/ProbeCommon.hlsl"
StructuredBuffer<DDGIVolumeDescGPUPacked> DDGIVolumes;
Texture2DArray<float4> gProbeData;
RWByteAddressBuffer gInstances;
RaytracingAccelerationStructure gProbeTLAS;
Texture2D<float> gSurfaceDistance;
Texture2D<float4> gViewW;
RWTexture2D<float4> gColor, gDirect;
cbuffer VisCB
{
    uint gCount;
    float gRadius;
    uint2 gFrameDim;
    float3 gOrigin;
    bool gHasView;
    float3 gCameraU;
    bool gHasDirect;
    float3 gCameraV;
    float3 gCameraW;
    float2 gJitter;
};
[numthreads(32,1,1)]
void updateInstances(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= gCount) return;
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    float3 p = DDGIGetProbeWorldPosition(DDGIGetProbeCoords(tid.x, volume), volume, gProbeData);
    uint address = tid.x * 64u;
    // First 48 bytes of RtInstanceDesc: row-major 3x4 transform. Preserve ID,
    // visibility mask and the shared BLAS address in the remaining 16 bytes.
    gInstances.Store4(address, asuint(float4(gRadius,0,0,p.x)));
    gInstances.Store4(address+16, asuint(float4(0,gRadius,0,p.y)));
    gInstances.Store4(address+32, asuint(float4(0,0,gRadius,p.z)));
}
[numthreads(8,8,1)]
void drawProbes(uint3 tid : SV_DispatchThreadID)
{
    uint2 p = tid.xy;
    if (any(p >= gFrameDim)) return;
    float2 ndc = ((float2(p)+.5f)/float2(gFrameDim)+gJitter)*float2(2,-2)+float2(-1,1);
    float3 direction = gHasView ? -gViewW[p].xyz : normalize(ndc.x*gCameraU + ndc.y*gCameraV + gCameraW);
    RayDesc ray;
    ray.Origin = gOrigin; ray.Direction = direction; ray.TMin = 0.f;
    ray.TMax = gSurfaceDistance[p];
    if (ray.TMax <= 0.f) return;
    RayQuery<RAY_FLAG_SKIP_TRIANGLES> query;
    query.TraceRayInline(gProbeTLAS, RAY_FLAG_NONE, 0xff, ray);
    while (query.Proceed())
    {
        if (query.CandidateType() == CANDIDATE_PROCEDURAL_PRIMITIVE)
        {
            float3 o = query.CandidateObjectRayOrigin(), d = query.CandidateObjectRayDirection();
            float a = dot(d,d), b = dot(o,d), c = dot(o,o)-1.f;
            float discriminant = b*b-a*c;
            if (discriminant < 0.f) continue;
            float t = (-b-sqrt(discriminant))/a;
            if (t > 0.f && t < ray.TMax) query.CommitProceduralPrimitiveHit(t);
        }
    }
    if (query.CommittedStatus() != COMMITTED_PROCEDURAL_PRIMITIVE_HIT) return;
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    int3 coords = DDGIGetProbeCoords(query.CommittedInstanceID(), volume);
    float3 center = DDGIGetProbeWorldPosition(coords, volume, gProbeData);
    float3 normal = normalize(gOrigin + direction*query.CommittedRayT()-center);
    int index = DDGIGetScrollingProbeIndex(coords, volume);
    float state = DDGILoadProbeState(index, gProbeData, volume);
    float3 tint = state == RTXGI_DDGI_PROBE_STATE_INACTIVE ? float3(.9f,.06f,.02f) : float3(.05f,.8f,.15f);
    float3 color = tint*(.25f+.75f*max(0.f,dot(normal,-direction)));
    gColor[p] = float4(color,1);
    // Reconstruct recognizes the marker and preserves an opaque full-res overlay.
    if (gHasDirect) gDirect[p] = float4(color,-1);
}
