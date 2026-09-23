// Static angular-weighted distance moments. The RT batch is reused by all texels.
import ProbeDistance;
StructuredBuffer<float4> gRays;
RWTexture2D<float4> gMoments;
cbuffer BlendCB
{
    uint gOffset;
    uint gCount;
    uint gResolution;
    uint gColumns;
    uint gBatch;
    float gExponent;
}

[numthreads(64, 1, 1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= gCount) return;
    uint linear = gOffset + tid.x;
    uint area = gResolution * gResolution;
    uint probe = linear / area;
    uint local = linear % area;
    uint2 texel = uint2(local % gResolution, local / gResolution);
    uint2 pixel = uint2(probe % gColumns, probe / gColumns) * (gResolution + 2) + texel + 1;
    float3 direction = probeOctDecode((float2(texel) + 0.5f) / float(gResolution));
    float4 previous = gMoments[pixel];
    float2 sum = previous.xy * previous.z;
    float total = previous.z;
    for (uint s = 0; s < gBatch; ++s)
    {
        float4 ray = gRays[probe * 16 + s];
        float weight = pow(saturate(dot(direction, ray.xyz)), gExponent);
        sum += weight * float2(ray.w, ray.w * ray.w);
        total += weight;
    }
    float2 moments = total > 1e-20f ? sum / total : float2(1.f);
    // Distances are normalized to [0,1]. Repeated weighted accumulation can
    // produce 1 + a few ulps in all-MISS directions. Repair only small finite
    // range errors; leave substantial corruption / non-finite values visible
    // to the cache validator instead of hiding them with unconditional saturate.
    if (all(isfinite(moments)) && all(moments >= -2e-5f) && all(moments <= 1.f + 2e-5f))
        moments = saturate(moments);
    // Discard subnormal-weight accumulations consistently with the fallback mean.
    gMoments[pixel] = total > 1e-20f ? float4(moments, total, 0.f) : float4(1, 1, 0, 0);
}
