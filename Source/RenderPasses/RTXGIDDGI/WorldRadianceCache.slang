// Shared DDGI world-radiance-cache definitions. The baseline tracer supplies
// scene/material/light evaluation and the unmodified SDK irradiance query.
// Cell keys use the Lumen World Cache layout (LumenWorldCache.slang): 8-bit
// wrapped cell coordinate per axis, 5-bit distance level and 3-bit dominant
// normal face. Material is deliberately NOT part of the key (idTech 8 style):
// surfaces of different materials in one cell share the representative result.
#ifndef FALCOR_DDGI_WORLD_RADIANCE_CACHE
#define FALCOR_DDGI_WORLD_RADIANCE_CACHE
#ifndef WRC_FINAL_GATHER_ONLY
#define WRC_FINAL_GATHER_ONLY 0
#endif
#if !WRC_FINAL_GATHER_ONLY
#include "RTXGIDDGI.rt.slang"
#include "WorldRadianceCacheStress.slang"
#endif

cbuffer WrcCB
{
    uint gWrcTableSize;
    uint gWrcMaxAge;        // Zero refreshes every occupied entry on every update.
    uint gWrcFrame;         // One-based probe update index, not presentation frame.
    float gWrcCellSize;     // Base cell width in world units (0.25 m).
    uint gWrcShadeSamples;
    uint gWrcBypassSharing; // Validation: original per-ray shading after tracing.
    float gWrcLodDistance;  // World units; level L covers [d(2^L - 1), d(2^(L+1) - 1)).
    uint gWrcMaxLod;        // Maximum cell-width multiplier, a power of two.
    uint gWrcProbeLimit;
    uint gWrcTypeCount;
    uint gWrcShaderBucket;
    uint gWrcRayCount;
    uint gWrcGroupByMaterial;
    uint gWrcStressMode;
    uint gWrcStressIterations;
    uint gWrcStressStats;
    float3 gWrcCamera;      // Camera position used for the distance level, fixed per frame.
    uint gWrcPadding;
}

// Host strides are exactly 64 and 32 bytes. A fixed uint4 accommodates both
// Falcor PackedHitInfo formats. Hits become immutable before hash insertion.
struct WrcHit
{
    uint4 packedHit;
    float3 direction;
    float hitT;
    uint key;       // Packed cell key, see wrcPackKey.
    uint level;     // Distance level; cell width is gWrcCellSize << level.
    uint materialID;
    uint valid; // 0: no lighting work; 1: cacheable; 2: per-ray fallback.
    int3 cell;      // Unwrapped cell coordinate, kept for the debug overlay only.
    uint shaderBucket;
};

// The debug overlay reads this 32-byte layout (WorldRadianceCacheDebug.slang).
struct WrcKey
{
    uint key;
    uint level;
    int3 cell;      // Unwrapped cell coordinate at this level, for visualization only.
    uint valid;
    uint padding0;
    uint padding1;
};

#if !WRC_FINAL_GATHER_ONLY
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
#else
// Final gather reads the cache produced by the latest probe update. Entries are
// resolved through the same probe window; nothing is written.
StructuredBuffer<WrcKey> gWrcKeys;
StructuredBuffer<float4> gWrcRadiance;
StructuredBuffer<uint> gWrcLastUpdate;
#endif

static const uint kWrcNoOwner = 0xffffffffu;
static const uint kWrcMaxLevel = 31u; // 5 key bits

uint wrcMix(uint value)
{
    value ^= value >> 16;
    value *= 0x7feb352du;
    value ^= value >> 15;
    value *= 0x846ca68bu;
    value ^= value >> 16;
    return value;
}

// Distance level as in idTech 8: lod = exp2(floor(log2(1 + d / LOD_DIST))).
uint wrcLevel(float3 position)
{
    float distance = length(position - gWrcCamera);
    bool validDistance = isfinite(distance) && isfinite(gWrcLodDistance) && gWrcLodDistance > 0.f;
    float level = validDistance ? floor(log2(1.f + distance / gWrcLodDistance)) : 0.f;
    uint maxLevel = min(firstbithigh(max(gWrcMaxLod, 1u)), kWrcMaxLevel);
    return min(uint(clamp(level, 0.f, float(kWrcMaxLevel))), maxLevel);
}

// Same face encoding as LumenWorldCache DirToCubeFaceIndex.
uint wrcFace(float3 n)
{
    float3 a = abs(n);
    uint axis = a.x >= a.y && a.x >= a.z ? 0u : (a.y >= a.z ? 1u : 2u);
    return axis * 2u + (n[axis] < 0.f ? 1u : 0u);
}

int3 wrcCell(float3 position, uint level)
{
    return int3(floor(position / (gWrcCellSize * float(1u << level))));
}

// Key layout of LumenWorldCache PackWorldCacheHashKey. Zero is reserved for
// "no entry" there; here empty slots are tracked by owner, so zero is valid.
uint wrcPackKey(int3 cell, uint level, uint face)
{
    uint3 wrapped = uint3(cell) & 0xffu;
    return wrapped.x | (wrapped.y << 8) | (wrapped.z << 16) | (level << 24) | (face << 29);
}

uint wrcKeyOf(float3 position, float3 normal, out uint level)
{
    level = wrcLevel(position);
    return wrcPackKey(wrcCell(position, level), level, wrcFace(normal));
}

uint wrcSlot(uint key)
{
    return wrcMix(key) % gWrcTableSize;
}

// Resolve a world-space point through the occupied slots of the latest update.
// Returns false on a miss or a stale/unshaded slot.
bool wrcLookup(float3 position, float3 normal, out float3 radiance)
{
    radiance = float3(0.f);
    if (gWrcTableSize == 0u) return false;
    uint level;
    uint key = wrcKeyOf(position, normal, level);
    uint firstSlot = wrcSlot(key);
    uint limit = min(gWrcProbeLimit, gWrcTableSize);
    for (uint probe = 0u; probe < limit; ++probe)
    {
        uint slot = (firstSlot + probe) % gWrcTableSize;
        WrcKey stored = gWrcKeys[slot];
        if (stored.valid == 0u) return false; // Never written since the last reset.
        if (stored.key == key && stored.level == level)
        {
            // Only entries shaded by the latest update (or reused within max age).
            uint lastUpdate = gWrcLastUpdate[slot];
            if (lastUpdate == 0u || gWrcFrame < lastUpdate || gWrcFrame - lastUpdate > gWrcMaxAge) return false;
            radiance = gWrcRadiance[slot].rgb;
            return all(isfinite(radiance));
        }
    }
    return false;
}

#if !WRC_FINAL_GATHER_ONLY
WrcKey wrcKey(WrcHit hit)
{
    WrcKey key = {};
    key.key = hit.key;
    key.level = hit.level;
    key.cell = hit.cell;
    key.valid = 1u;
    return key;
}

bool wrcSameKey(WrcKey a, WrcKey b)
{
    return a.key == b.key && a.level == b.level;
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
#endif // !WRC_FINAL_GATHER_ONLY
#endif
