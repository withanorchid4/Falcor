#include "LumenWorldCache.slang"
[numthreads(256, 1, 1)]
void resolve(uint3 id : SV_DispatchThreadID)
{
    uint slot = id.x;
    if (slot >= gWCSize || gWCState[slot] != 2u) return;
    uint4 sum = gWCAccumulation[slot];
    if (sum.w > 0u)
    {
        float4 previous = gWCLighting[slot];
        float history = min(previous.w + 1.f, float(gWCHistory));
        float3 sample = asfloat(sum.xyz) / float(sum.w);
        gWCLighting[slot] = float4(lerp(previous.rgb, sample, 1.f / history), history);
        gWCAge[slot] = 0u;
    }
    else if (++gWCAge[slot] >= gWCMaxAge)
    {
        gWCLighting[slot] = float4(0.f);
        gWCState[slot] = 0u;
    }
    gWCAccumulation[slot] = uint4(0u);
    if (gWCState[slot] == 2u) InterlockedAdd(gWCStats[3], 1u);
}
