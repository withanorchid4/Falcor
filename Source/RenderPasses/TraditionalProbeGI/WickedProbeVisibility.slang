// Adapted from WickedEngine df75fbd1, ShaderInterop_DDGI.h and ddgi_raytraceCS.hlsl.
// MIT: see WickedEngine-LICENSE.txt. Static SH9 integration; no relocation/history.
float3 wickedFibonacciDirection(uint sampleIndex)
{
    float phase = frac(float(sampleIndex) * 0.618033988749895f);
    // Large float products quantize the fractional golden-angle phase. Use modulo-2^32
    // fixed-point for high-count experiments; preserve the existing default ray sequence.
    if (gWickedRayCount > 65536)
        phase = float((sampleIndex * 0x9e3779b9u) >> 8) * (1.f / 16777216.f);
    float phi = 6.28318530718f * phase;
    float z = 1.f - (2.f * float(sampleIndex) + 1.f) / float(gWickedRayCount);
    float r = sqrt(max(0.f, 1.f - z * z));
    return float3(cos(phi) * r, sin(phi) * r, z);
}
void bakeWickedRays(uint index)
{
    uint3 grid = uint3(index % gGridCounts.x, (index / gGridCounts.x) % gGridCounts.y,
        index / (gGridCounts.x * gGridCounts.y));
    float3 origin = lerp(gGridMin, gGridMax, float3(grid) / float3(gGridCounts - 1));
    for (uint s = 0; s < gSampleBatch; ++s)
    {
        float3 direction = wickedFibonacciDirection(gSampleStart + s);
        ScatterRayData payload = ScatterRayData(SampleGenerator(uint2(0), 0));
        payload.distanceOnly = true;
        payload.firstHitDistance = -1.f;
        RayDesc ray;
        ray.Origin = origin; ray.Direction = direction; ray.TMin = 0.f; ray.TMax = FLT_MAX;
        TraceRay(gScene.rtAccel, RAY_FLAG_FORCE_OPAQUE | RAY_FLAG_SKIP_PROCEDURAL_PRIMITIVES, 0xff, 0, rayTypeCount, 0, ray, payload);
        float hit = payload.firstHitDistance;
        float depth = hit > 0.f ? clamp(hit - 0.01f, 0.f, gDistanceMax) : gDistanceMax;
        gWickedRays[index * 16 + s] = float4(direction, depth);
    }
}
float2 wickedMoments(uint index, float3 direction)
{
    uint tileSize = gDistanceResolution + 2;
    uint columns = gDistanceAtlasSize.x / tileSize;
    float2 pixel = float2(uint2(index % columns, index / columns) * tileSize + 1) + probeOctEncode(direction) * float(gDistanceResolution);
    return gWickedMoments.SampleLevel(gWickedSampler, pixel / float2(gDistanceAtlasSize), 0);
}
uint3 wickedCell(float3 P, float3 N, out float3 t, out float3 Q, out bool clamped)
{
    Q = P + N * gWickedNormalBias;
    float3 spacing = (gGridMax - gGridMin) / float3(gGridCounts - 1);
    float3 raw = (P - gGridMin) / spacing;
    clamped = any(raw < 0.f) || any(raw > float3(gGridCounts - 1));
    float3 q = clamp(raw, float3(0), float3(gGridCounts - 1));
    uint3 cell = min(uint3(floor(q)), gGridCounts - 2);
    t = q - float3(cell);
    return cell;
}
float wickedVisibility(float distance, float2 moments)
{
    if (distance <= moments.x) return 1.f;
    float delta = distance - moments.x;
    float variance = abs(moments.y - moments.x * moments.x);
    float denominator = variance + delta * delta;
    float p = denominator > 0.f ? variance / denominator : 0.f;
    return p * p * p;
}
float wickedCornerWeight(float3 P, float3 N, float3 Q, uint3 cell, float3 t, uint corner,
    out float trilinear, out float visibility, out float4 distanceInfo)
{
    uint3 offset = uint3(corner & 1, (corner >> 1) & 1, (corner >> 2) & 1);
    float3 factors = lerp(1.f - t, t, float3(offset));
    trilinear = factors.x * factors.y * factors.z;
    float3 probe = lerp(gGridMin, gGridMax, float3(cell + offset) / float3(gGridCounts - 1));
    float3 delta = Q - probe;
    float d = length(delta);
    float3 direction = d > 1e-8f ? delta / d : float3(0, 0, 1);
    float2 moments = gHasBakedData ? wickedMoments(flattenProbe(cell + offset), direction) : float2(gDistanceMax, gDistanceMax * gDistanceMax);
    visibility = wickedVisibility(d, moments);
    if (gUseVisibility && gRayTracedVisibility && gHasBakedData)
        visibility = trilinear > 0.f ? traceProbeVisibility(probe, Q) : 0.f;
    float3 trueDelta = probe - P;
    float cosine = dot(N, trueDelta / max(length(trueDelta), 1e-8f));
    float wrap = max(0.0001f, (cosine + 1.f) * 0.5f);
    float normalWeight = gUseNormalWeight ? lerp(saturate(dot(-direction, N)), wrap * wrap + 0.2f, gWickedSmoothBackface) : 1.f;
    distanceInfo = float4(moments.x, abs(moments.y - moments.x * moments.x), d, normalWeight);
    if (!gUseVisibility || !gHasBakedData) return trilinear;
    // The ray backend is a strict diagnostic extension: never resurrect blocked probes.
    if (gRayTracedVisibility && visibility == 0.f) return 0.f;
    float support = max(0.01f, normalWeight * visibility);
    if (support < 0.2f) support *= support * support / 0.04f;
    return trilinear * support;
}
