// Compute lighting uses inline visibility queries; no TraceRay call is reachable
// from these entry points. Scene TLAS data must be bound for ray queries.
#define DDGI_INLINE_SHADOW 1
#include "WorldRadianceCache.slang"

[numthreads(64, 1, 1)]
void buildWRC(uint3 dispatchThreadID : SV_DispatchThreadID)
{
    uint rayID = dispatchThreadID.x + dispatchThreadID.y * (65535u * 64u);
    if (rayID >= gWrcRayCount) return;
    uint batchProbe = rayID / uint(UnpackDDGIVolumeDescGPU(DDGIVolumes[0]).probeNumRays);
    uint3 batchCounts = uint3(UnpackDDGIVolumeDescGPU(DDGIVolumes[0]).probeCounts);
    uint batchTotal = batchCounts.x * batchCounts.y * batchCounts.z;
    if ((batchProbe + batchTotal - gProbeBatchStart) % batchTotal >= gProbeBatchCount) return;
    gWrcRaySlots[rayID] = kWrcNoOwner;
    WrcHit hit = gWrcHits[rayID];
    if (hit.valid != 1u || gWrcBypassSharing != 0u) return;
    WrcKey key = wrcKey(hit);
    uint firstSlot = wrcSlot(key.key);
    uint limit = min(gWrcProbeLimit, gWrcTableSize);
    uint steps = 0u;
    for (uint probe = 0u; probe < limit; ++probe)
    {
        uint slot = (firstSlot + probe) % gWrcTableSize;
        uint owner;
        InterlockedCompareExchange(gWrcOwners[slot], kWrcNoOwner, rayID, owner);
        ++steps;
        if (owner == kWrcNoOwner)
        {
            // The CAS publishes an ID into an already completed hit buffer.
            // Readers never wait for a winning thread to finish writing a key.
            uint activeIndex;
            uint listBucket = gWrcGroupByMaterial != 0u ? hit.shaderBucket : 0u;
            InterlockedAdd(gWrcActiveCounts[listBucket], 1u, activeIndex);
            gWrcActiveSlots[listBucket * gWrcTableSize + activeIndex] = slot;
            gWrcRaySlots[rayID] = slot;
            InterlockedAdd(gWrcCounters[1], 1u);
            InterlockedAdd(gWrcCounters[7], steps);
            return;
        }
        if (wrcSameKey(key, wrcKey(gWrcHits[owner])))
        {
            gWrcRaySlots[rayID] = slot;
            InterlockedAdd(gWrcCounters[7], steps);
            return;
        }
    }
    // Engineering adaptation: bounded-probe exhaustion falls back to original
    // per-ray shading to preserve energy, rather than discarding the sample.
    InterlockedAdd(gWrcCounters[7], steps);
    InterlockedAdd(gWrcCounters[8], 1u);
}

[numthreads(1, 1, 1)]
void prepareWRC(uint3 dispatchThreadID : SV_DispatchThreadID)
{
    uint bucket = dispatchThreadID.x;
    uint dispatchCount = gWrcGroupByMaterial != 0u ? gWrcTypeCount : 1u;
    if (bucket >= dispatchCount) return;
    uint count = min(gWrcActiveCounts[bucket], gWrcTableSize);
    gWrcDispatchArgs.Store3(bucket * 12u, uint3((count + 63u) / 64u, 1u, 1u));
}

// Visit a shader-type list, or the single mixed list with grouping disabled.
// Every occupied slot has exactly one writer after all insertion is complete.
[numthreads(64, 1, 1)]
void shadeWRC(uint3 dispatchThreadID : SV_DispatchThreadID)
{
    uint bucket = gWrcShaderBucket;
    uint dispatchCount = gWrcGroupByMaterial != 0u ? gWrcTypeCount : 1u;
    if (bucket >= dispatchCount || gWrcBypassSharing != 0u) return;
    uint activeIndex = dispatchThreadID.x;
    if (activeIndex >= gWrcActiveCounts[bucket]) return;
    uint slot = gWrcActiveSlots[bucket * gWrcTableSize + activeIndex];
    uint owner = gWrcOwners[slot];
    if (owner >= gWrcRayCount) return;
    WrcHit hit = gWrcHits[owner];
    if (hit.valid != 1u || (gWrcGroupByMaterial != 0u && hit.shaderBucket != bucket)) return;
    WrcKey key = wrcKey(hit);
    uint lastUpdate = gWrcLastUpdate[slot];
    bool reuse = false;
    if (gWrcFrame > 32u && gWrcMaxAge > 0u && lastUpdate != 0u &&
        gWrcFrame >= lastUpdate && gWrcFrame - lastUpdate <= gWrcMaxAge)
    {
        if (wrcSameKey(key, gWrcKeys[slot]))
        {
            reuse = all(isfinite(gWrcRadiance[slot].rgb));
            if (!reuse) InterlockedAdd(gWrcCounters[6], 1u);
        }
    }
    if (reuse)
    {
        // Reading an entry must not extend the timestamp of its last shading.
        InterlockedAdd(gWrcCounters[5], 1u);
        return;
    }
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    uint stressChecksum;
    float3 radiance = wrcShadeHit(hit, owner, gWrcShadeSamples, volume, stressChecksum);
    // An observable UAV store keeps the synthetic recurrence alive, even when
    // wave diagnostics are disabled. Only RGB is consumed by the lighting path.
    gWrcRadiance[slot] = float4(radiance, float(stressChecksum & 0x00ffffffu));
    if (gWrcStressStats != 0u)
    {
        uint types = WaveActiveBitOr(1u << min(hit.shaderBucket, 31u));
        uint checksum = WaveActiveBitXor(stressChecksum);
        uint lanes = WaveActiveCountBits(true);
        if (WaveIsFirstLane())
        {
            InterlockedAdd(gWrcCounters[12], countbits(types));
            InterlockedAdd(gWrcCounters[13], 1u);
            InterlockedXor(gWrcCounters[14], checksum);
#if WRC_STRESS_ENABLED
            InterlockedAdd(gWrcCounters[15], lanes);
#endif
        }
    }
    gWrcKeys[slot] = key;
    gWrcLastUpdate[slot] = gWrcFrame;
    InterlockedAdd(gWrcCounters[2], 1u);
}

[numthreads(64, 1, 1)]
void gatherWRC(uint3 dispatchThreadID : SV_DispatchThreadID)
{
    uint rayID = dispatchThreadID.x + dispatchThreadID.y * (65535u * 64u);
    if (rayID >= gWrcRayCount) return;
    uint batchProbe = rayID / uint(UnpackDDGIVolumeDescGPU(DDGIVolumes[0]).probeNumRays);
    uint3 batchCounts = uint3(UnpackDDGIVolumeDescGPU(DDGIVolumes[0]).probeCounts);
    uint batchTotal = batchCounts.x * batchCounts.y * batchCounts.z;
    if ((batchProbe + batchTotal - gProbeBatchStart) % batchTotal >= gProbeBatchCount) return;
    WrcHit hit = gWrcHits[rayID];
    if (hit.valid == 0u) return;
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    uint slot = gWrcRaySlots[rayID];
    uint owner = kWrcNoOwner;
    bool served = false;
    float3 radiance = float3(0.f);
    if (hit.valid == 1u && gWrcBypassSharing == 0u && slot < gWrcTableSize)
    {
        owner = gWrcOwners[slot];
        if (owner < gWrcRayCount && gWrcLastUpdate[slot] != 0u && wrcSameKey(wrcKey(hit), gWrcKeys[slot]))
        {
            radiance = gWrcRadiance[slot].rgb;
            served = all(isfinite(radiance));
            if (!served) InterlockedAdd(gWrcCounters[6], 1u);
        }
    }
    if (served)
    {
        InterlockedAdd(gWrcCounters[3], 1u);
        TriangleHit triangle = HitInfo(wrcUnpackHit(hit)).getTriangleHit();
        TriangleHit ownerTriangle = HitInfo(wrcUnpackHit(gWrcHits[owner])).getTriangleHit();
        if (triangle.instanceID.index != ownerTriangle.instanceID.index || triangle.primitiveIndex != ownerTriangle.primitiveIndex)
            InterlockedAdd(gWrcCounters[11], 1u);
    }
    else
    {
        uint stressChecksum;
        radiance = wrcShadeHit(hit, rayID, 1u, volume, stressChecksum);
        // Preserve synthetic work for rare overflow fallback too.
#if WRC_STRESS_ENABLED
        InterlockedXor(gWrcCounters[14], stressChecksum);
#endif
        InterlockedAdd(gWrcCounters[4], 1u);
    }
    uint rayIndex, probeIndex;
    wrcRayIndices(rayID, volume, rayIndex, probeIndex);
    uint3 outputCoords = DDGIGetRayDataTexelCoords(int(rayIndex), int(probeIndex), volume);
    // Distances are never shared: SDK visibility, relocation and classification
    // still receive the original geometry distance of every individual ray.
    DDGIStoreProbeRayFrontfaceHit(gRayData, outputCoords, volume, finiteRadiance(radiance, 3u), hit.hitT);
}
