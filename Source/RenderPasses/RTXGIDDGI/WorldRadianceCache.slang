// Shared DDGI world-radiance-cache definitions. The baseline tracer supplies
// scene/material/light evaluation and the unmodified SDK irradiance query.
#ifndef FALCOR_DDGI_WORLD_RADIANCE_CACHE
#define FALCOR_DDGI_WORLD_RADIANCE_CACHE
#include "RTXGIDDGI.rt.slang"
#include "WorldRadianceCacheStress.slang"

cbuffer WrcCB
{
    uint gWrcTableSize;
    uint gWrcMaxAge;        // Zero refreshes every occupied entry on every update.
    uint gWrcFrame;         // One-based probe update index, not presentation frame.
    float gWrcCellSize;
    uint gWrcShadeSamples;
    uint gWrcBypassSharing; // Validation: original per-ray shading after tracing.
    float gWrcLodDistance;
    uint gWrcMaxLod;
    uint gWrcProbeLimit;
    uint gWrcTypeCount;
    uint gWrcShaderBucket;
    uint gWrcRayCount;
    uint gWrcGroupByMaterial;
    uint gWrcStressMode;
    uint gWrcStressIterations;
    uint gWrcStressStats;
}

// Host strides are exactly 64 and 32 bytes. A fixed uint4 accommodates both
// Falcor PackedHitInfo formats. Hits become immutable before hash insertion.
struct WrcHit
{
    uint4 packedHit;
    float3 direction;
    float hitT;
    int3 cell;
    uint lod;
    uint materialID;
    uint normalKey;
    uint valid; // 0: no lighting work; 1: cacheable; 2: per-ray fallback.
    uint shaderBucket;
};

struct WrcKey
{
    int3 cell;
    uint lod;
    uint materialID;
    uint normalKey;
    uint shaderBucket;
    uint padding;
};

RWStructuredBuffer<WrcHit> gWrcHits;
RWStructuredBuffer<uint> gWrcOwners;
RWStructuredBuffer<WrcKey> gWrcKeys;
RWStructuredBuffer<float4> gWrcRadiance;
RWStructuredBuffer<uint> gWrcLastUpdate;
RWStructuredBuffer<uint> gWrcRaySlots;
RWStructuredBuffer<uint> gWrcActiveSlots;
RWStructuredBuffer<uint> gWrcActiveCounts;
RWByteAddressBuffer gWrcDispatchArgs;
StructuredBuffer<uint> gWrcTypeMap;
// 0 eligible rays, 1 occupied entries, 2 shaded entries, 3 served rays,
// 4 fallback rays, 5 temporal entries, 6 non-finite results, 7 probe steps,
// 8 exhausted rays, 9 maximum LOD, 10 coarse-LOD rays, 11 cross-geometry rays.
// Optional diagnostics: 12 wave type sum, 13 wave count, 14 checksum XOR,
// 15 stressed entries. These exclude gather fallback invocations.
RWStructuredBuffer<uint> gWrcCounters;

static const uint kWrcNoOwner = 0xffffffffu;

uint wrcMix(uint value)
{
    value ^= value >> 16;
    value *= 0x7feb352du;
    value ^= value >> 15;
    value *= 0x846ca68bu;
    value ^= value >> 16;
    return value;
}

WrcKey wrcKey(WrcHit hit)
{
    WrcKey key = {};
    key.cell = hit.cell;
    key.lod = hit.lod;
    key.materialID = hit.materialID;
    key.normalKey = hit.normalKey;
    key.shaderBucket = hit.shaderBucket;
    return key;
}

bool wrcSameKey(WrcKey a, WrcKey b)
{
    return all(a.cell == b.cell) && a.lod == b.lod && a.materialID == b.materialID &&
        a.normalKey == b.normalKey && a.shaderBucket == b.shaderBucket;
}

uint wrcSlot(WrcKey key)
{
    // Nested LOD/position hashing follows the spatial cache layout. Material
    // and oriented geometric normal prevent unrelated surfaces sharing a cell.
    uint hash = wrcMix(key.lod + wrcMix(asuint(key.cell.z) +
        wrcMix(asuint(key.cell.y) + wrcMix(asuint(key.cell.x)))));
    hash = wrcMix(hash ^ key.materialID);
    hash = wrcMix(hash ^ key.normalKey);
    hash = wrcMix(hash ^ key.shaderBucket);
    return hash % gWrcTableSize;
}

uint wrcPackNormal(float3 normal)
{
    uint3 encoded = uint3(saturate(normalize(normal) * 0.5f + 0.5f) * 31.f + 0.5f);
    return encoded.x | (encoded.y << 5) | (encoded.z << 10);
}

PackedHitInfo wrcUnpackHit(WrcHit hit)
{
#if HIT_INFO_USE_COMPRESSION
    return hit.packedHit.xy;
#else
    return hit.packedHit;
#endif
}

void wrcRayIndices(uint linearRayID, DDGIVolumeDescGPU volume, out uint rayIndex, out uint probeIndex)
{
    rayIndex = linearRayID % uint(volume.probeNumRays);
    uint logicalProbeIndex = linearRayID / uint(volume.probeNumRays);
    int3 probeCoords = DDGIGetProbeCoords(int(logicalProbeIndex), volume);
    probeIndex = uint(DDGIGetScrollingProbeIndex(probeCoords, volume));
}

// One sample uses the original ray/probe/frame stream. The baseline diffuse
// direct estimator and historical DDGI feedback remain unchanged.
float3 wrcShadeHit(WrcHit hit, uint linearRayID, uint sampleCount, DDGIVolumeDescGPU volume, out uint stressChecksum)
{
    stressChecksum = 0u;
    ShadingData sd = loadTriangleSurface(HitInfo(wrcUnpackHit(hit)), hit.direction);
    if (!validSurface(sd)) return float3(0.f);
    let material = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f));
#if WRC_STRESS_ENABLED
    // Isolated synthetic proxy for expensive type-specific pattern generation.
    // It deliberately leaves the real material implementations and RGB intact.
    uint seed = asuint(sd.posW.x) ^ asuint(sd.posW.y) ^ asuint(sd.posW.z) ^ linearRayID;
    stressChecksum = wrcStress(seed, gWrcStressMode == 1u ? 0u : hit.shaderBucket % 11u, gWrcStressIterations);
#endif
    let properties = material.getProperties(sd);
    uint rayIndex, probeIndex;
    wrcRayIndices(linearRayID, volume, rayIndex, probeIndex);
    SampleGenerator sg = SampleGenerator(uint2(rayIndex, probeIndex), gFrameCount);
    sampleCount = clamp(sampleCount, 1u, 8u);
    float3 radiance = float3(0.f);
    for (uint sampleIndex = 0; sampleIndex < sampleCount; ++sampleIndex)
        radiance += evaluateDirect(sd, material, true, sg);
    radiance /= float(sampleCount);
    if (gHistoryValid)
    {
        float3 irradiance = queryIrradiance(sd.posW, sd.getOrientedFaceNormal(), hit.direction, volume);
        float3 albedo = finiteRadiance(properties.diffuseReflectionAlbedo, 0u);
        radiance += min(albedo, float3(0.9f)) * irradiance / M_PI;
    }
    if (!all(isfinite(radiance))) InterlockedAdd(gWrcCounters[6], 1u);
    return finiteRadiance(radiance, 3u);
}
#endif
