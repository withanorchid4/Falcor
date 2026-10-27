// Geometry-only phase. Lighting and hash insertion consume completed immutable
// hit records in separate compute dispatches with host-issued UAV barriers.
#include "WorldRadianceCache.slang"

[shader("raygeneration")]
void traceWRC()
{
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    uint3 launch = DispatchRaysIndex();
    int rayIndex = int(launch.x);
    int logicalProbeIndex = int(launch.z) * DDGIGetProbesPerPlane(volume.probeCounts) + int(launch.y);
    int probeCount = volume.probeCounts.x * volume.probeCounts.y * volume.probeCounts.z;
    if (rayIndex >= volume.probeNumRays || logicalProbeIndex >= probeCount) return;
    uint linearRayID = uint(logicalProbeIndex * volume.probeNumRays + rayIndex);
    if (linearRayID >= gWrcRayCount) return;
    WrcHit hit = {};
    gWrcHits[linearRayID] = hit;
    int3 probeCoords = DDGIGetProbeCoords(logicalProbeIndex, volume);
    int probeIndex = DDGIGetScrollingProbeIndex(probeCoords, volume);

    float state = DDGILoadProbeState(probeIndex, gProbeData, volume);
    if (state == RTXGI_DDGI_PROBE_STATE_INACTIVE && rayIndex >= RTXGI_DDGI_NUM_FIXED_RAYS) return;

    float3 direction = DDGIGetProbeRayDirection(rayIndex, volume);
    uint3 outputCoords = DDGIGetRayDataTexelCoords(rayIndex, probeIndex, volume);
    RayDesc ray;
    ray.Origin = DDGIGetProbeWorldPosition(probeCoords, volume, gProbeData);
    ray.Direction = direction;
    ray.TMin = 0.f;
    ray.TMax = volume.probeMaxRayDistance;
    ProbeRayPayload payload = {};
    payload.hitT = -1.f;
    TraceRay(gScene.rtAccel, RAY_FLAG_NONE, 0xff, 0, rayTypeCount, 0, ray, payload);

    if (payload.hitT < 0.f)
    {
        DDGIStoreProbeRayMiss(gRayData, outputCoords, volume, float3(0.f));
        return;
    }
    if (payload.backFace != 0)
    {
        DDGIStoreProbeRayBackfaceHit(gRayData, outputCoords, volume, payload.hitT);
        return;
    }
    if ((volume.probeRelocationEnabled || volume.probeClassificationEnabled) && rayIndex < RTXGI_DDGI_NUM_FIXED_RAYS)
    {
        DDGIStoreProbeRayFrontfaceHit(gRayData, outputCoords, volume, payload.hitT);
        return;
    }

    ShadingData sd = loadTriangleSurface(HitInfo(payload.hit), direction);
    if (!validSurface(sd))
    {
        DDGIStoreProbeRayFrontfaceHit(gRayData, outputCoords, volume, float3(0.f), payload.hitT);
        return;
    }
    const TriangleHit triangle = HitInfo(payload.hit).getTriangleHit();
#if HIT_INFO_USE_COMPRESSION
    hit.packedHit = uint4(payload.hit, 0u, 0u);
#else
    hit.packedHit = payload.hit;
#endif
    hit.direction = direction;
    hit.hitT = payload.hitT;
    hit.materialID = gScene.getMaterialID(triangle.instanceID);
    hit.normalKey = wrcPackNormal(sd.getOrientedFaceNormal());
    uint typeMapCount, typeMapStride;
    gWrcTypeMap.GetDimensions(typeMapCount, typeMapStride);
    uint materialType = uint(gScene.materials.getMaterialType(hit.materialID));
    hit.shaderBucket = materialType < typeMapCount ? gWrcTypeMap[materialType] : kWrcNoOwner;

    float cameraDistance = length(sd.posW - gScene.camera.getPosition());
    bool validDistance = isfinite(cameraDistance) && isfinite(gWrcLodDistance) && gWrcLodDistance > 0.f;
    float lodExponent = validDistance ? floor(log2(1.f + cameraDistance / gWrcLodDistance)) : 0.f;
    hit.lod = min(1u << uint(clamp(lodExponent, 0.f, 6.f)), max(gWrcMaxLod, 1u));
    float3 cell = floor(sd.posW / (gWrcCellSize * float(hit.lod)));
    // Unknown shader types or nonrepresentable cells retain the original
    // per-ray estimator instead of accidentally aliasing a valid cache key.
    bool quantizable = validDistance && all(isfinite(cell)) && all(abs(cell) < 2147480000.f);
    hit.cell = quantizable ? int3(cell) : int3(0);
    hit.valid = quantizable && hit.shaderBucket < gWrcTypeCount ? 1u : 2u;
    gWrcHits[linearRayID] = hit;
    InterlockedAdd(gWrcCounters[0], 1u);
    InterlockedMax(gWrcCounters[9], hit.lod);
    if (hit.lod > 1u) InterlockedAdd(gWrcCounters[10], 1u);
}
