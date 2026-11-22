// This software contains source code provided by NVIDIA Corporation.
// SDK remains unmodified and is deployed by CMake from a pinned release.
#ifndef FALCOR_SHARC_CACHE
#define FALCOR_SHARC_CACHE
#define SHARC_MATERIAL_DEMODULATION 1
#define SHARC_SEPARATE_EMISSIVE 0
#define SHARC_ENABLE_RESPONSIVE_LIGHTING 0
#define SHARC_ENABLE_GLSL 0
#include "SHARC/SharcCommon.h"
cbuffer SharcCB
{
    uint gSharcSize;
    uint gSharcDownsample;
    uint gSharcBounces;
    uint gSharcHistory;
    uint gSharcFrame;
    float gSharcScale;
    float2 gSharcPixelOffset;
    float3 gSharcCamera;
    float3 gSharcPreviousCamera;
};
RWStructuredBuffer<uint64_t> gSharcHash;
RWStructuredBuffer<SharcAccumulationData> gSharcAccum;
RWStructuredBuffer<SharcPackedData> gSharcResolved;
RWStructuredBuffer<uint> gSharcStats; // queries, hits, occupied, nonfinite
SharcParameters sharcParameters()
{
    SharcParameters p;
    p.hashGridParameters.cameraPosition = gSharcCamera;
    p.hashGridParameters.logarithmBase = 2.f;
    p.hashGridParameters.sceneScale = gSharcScale;
    // Match WorldCache's .025 * 2^floor(log2(distance/(.025*density))).
    p.hashGridParameters.levelBias = 1.f - log2(.025f * gSharcScale);
    p.hashGridData.capacity = gSharcSize;
    p.hashGridData.hashEntriesBuffer = gSharcHash;
    p.accumulationBuffer = gSharcAccum;
    p.resolvedBuffer = gSharcResolved;
    p.radianceScale = 1000.f;
    return p;
}
SharcHitData sharcHit(float3 p, float3 n, float3 diffuseAlbedo)
{
    SharcHitData h;
    h.positionWorld = p; h.normalWorld = n;
    // RTXGI sample demodulation for Lambert (specular F0=0):
    // max(diffuse,.05) + max(F0,.02)*luma(F0+(1-F0)/21).
    h.materialDemodulation = max(diffuseAlbedo, .05f) + .02f / 21.f;
    return h;
}
bool sharcLookup(SharcHitData hitData, out float3 radiance)
{
    InterlockedAdd(gSharcStats[0], 1u);
    bool hit = SharcGetCachedRadiance(sharcParameters(), hitData, radiance, false);
    if (hit) InterlockedAdd(gSharcStats[1], 1u);
    return hit;
}
#endif
