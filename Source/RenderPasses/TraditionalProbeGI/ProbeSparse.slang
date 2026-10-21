// Screen-space scheduling and reconstruction only. All visibility and probe
// blending lives in sampleProbeIrradiance(), shared with the full-resolution path.
// No history: every valid cache texel is rebuilt before it can be consumed.
uint2 sparsePixel(uint2 index)
{
    return min(index * gSparseStride + gSparseStride / 2, gFrameDim - 1);
}

#ifndef SPARSE_RESOLVE_ONLY
void buildSparseSample(uint2 index)
{
    uint2 pixel = sparsePixel(index);
    HitInfo hit = HitInfo(gVBuffer[pixel]);
    gSparseIrradiance[index] = float4(0);
    if (!hit.isValid()) return;
    float3 direction = getPrimaryRayDir(pixel, gFrameDim, gScene.camera);
    ShadingData sd = loadShadingData(hit, gScene.camera.getPosition(), direction);
    if (gScene.materials.getMaterialHeader(sd.materialID).getAlphaMode() == AlphaMode::Mask) return;
    gSparseIrradiance[index] = float4(sampleProbeIrradiance(sd.posW, sd.frame.N), 1);
    gSparsePosition[index] = float4(sd.posW, 1);
    gSparseNormal[index] = float4(sd.frame.N, 1);
}
#endif

bool reconstructSparse(uint2 pixel, float3 position, float3 normal, uint materialID, out float3 irradiance)
{
    irradiance = float3(0);
    if (gScene.materials.getMaterialHeader(materialID).getAlphaMode() == AlphaMode::Mask) return false;
    // Do not extrapolate at the screen boundary: a missing neighbor may hide a thin shadow.
    if (any(pixel < gSparseStride / 2) || any(pixel >= gFrameDim - gSparseStride / 2)) return false;
    PackedHitInfo surfaceHit = gVBuffer[pixel];
    float2 uv = (float2(pixel) - float(gSparseStride / 2)) / float(gSparseStride);
    int2 base = int2(floor(uv));
    float2 t = frac(uv);
    float3 spacing = (gGridMax - gGridMin) / float3(gGridCounts - 1);
    float minSpacing = min(spacing.x, min(spacing.y, spacing.z));
    float planeTolerance = max(1e-5f, minSpacing * 0.005f);
    float maxDistance = minSpacing * 0.5f;
    float total = 0.f;
    irradiance = float3(0);
    float3 low = float3(FLT_MAX), high = float3(0);
    for (uint i = 0; i < 4; ++i)
    {
        uint2 offset = uint2(i & 1, i >> 1);
        float2 factors = lerp(1.f - t, t, float2(offset));
        float weight = factors.x * factors.y;
        if (weight <= 1e-6f) continue;
        uint2 index = uint2(clamp(base + int2(offset), int2(0), int2(gSparseDim) - 1));
        PackedHitInfo neighborHit = gVBuffer[sparsePixel(index)];
        // Header contains type, instance and primitive, without barycentrics.
        // Prevent nearby coplanar leaves/thin objects from sharing irradiance.
#if HIT_INFO_USE_COMPRESSION
        if (surfaceHit.x != neighborHit.x) return false;
#else
        if (any(surfaceHit.xy != neighborHit.xy)) return false;
#endif
        float4 e = gSparseIrradiance[index];
        if (e.w == 0.f) return false;
        float3 p = gSparsePosition[index].xyz;
        float3 n = gSparseNormal[index].xyz;
        float3 delta = position - p;
        if (dot(normal, n) < 0.995f || abs(dot(delta, normal)) > planeTolerance ||
            abs(dot(delta, n)) > planeTolerance || dot(delta, delta) > maxDistance * maxDistance) return false;
        irradiance += weight * e.xyz;
        total += weight;
        low = min(low, e.xyz);
        high = max(high, e.xyz);
    }
    // Do not interpolate missing surfaces or steep irradiance transitions.
    // This is a quality heuristic, not an exact visibility guarantee at every pixel.
    if (total < 0.999f || any(high - low > 0.15f * max(high, float3(0.02f)))) return false;
    irradiance /= total;
    return true;
}
