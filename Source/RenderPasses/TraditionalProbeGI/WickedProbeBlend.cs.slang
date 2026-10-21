// Static adaptation of WickedEngine ddgi_updateCS.hlsl. See WickedEngine-LICENSE.txt.
import ProbeDistance;
StructuredBuffer<float4> gRays;
RWTexture2D<float4> gAccumulation;
RWTexture2D<float2> gFinal;
cbuffer WickedBlendCB
{
    float gExponent;
    uint gResolution;
    uint gProbeCount;
    uint gColumns;
    uint gBatch;
    float gMaxDistance;
}
[numthreads(64, 1, 1)]
void blend(uint3 tid : SV_DispatchThreadID)
{
    uint linear = tid.x + tid.y * 65536;
    uint area = gResolution * gResolution;
    if (linear >= gProbeCount * area) return;
    uint probe = linear / area;
    uint local = linear % area;
    uint2 texel = uint2(local % gResolution, local / gResolution);
    uint2 pixel = uint2(probe % gColumns, probe / gColumns) * (gResolution + 2) + texel + 1;
    float3 direction = probeOctDecode((float2(texel) + 0.5f) / float(gResolution));
    float4 sum = gAccumulation[pixel];
    for (uint s = 0; s < gBatch; ++s)
    {
        float4 ray = gRays[probe * 16 + s];
        float weight = pow(saturate(dot(direction, ray.xyz)), gExponent);
        if (weight <= 0.0001f) continue;
        sum.xy += weight * float2(ray.w, ray.w * ray.w);
        sum.z += weight;
    }
    gAccumulation[pixel] = sum;
}
[numthreads(64, 1, 1)]
void finalize(uint3 tid : SV_DispatchThreadID)
{
    uint linear = tid.x + tid.y * 65536;
    uint tileSize = gResolution + 2;
    uint area = tileSize * tileSize;
    if (linear >= gProbeCount * area) return;
    uint probe = linear / area;
    uint2 tile = uint2(probe % gColumns, probe / gColumns) * tileSize;
    uint local = linear % area;
    uint2 padded = uint2(local % tileSize, local / tileSize);
    int2 texel = probeOctWrap(int2(padded) - 1, int(gResolution));
    float4 sum = gAccumulation[tile + uint2(texel) + 1];
    gFinal[tile + padded] = sum.z > 0.0001f ? sum.xy / sum.z : float2(gMaxDistance, gMaxDistance * gMaxDistance);
}
