// Falcor adaptation of the world-space surface-radiance cache algorithm.
// Engine integration is independent of UE; no surface cards or DDGI probes.
// Explicit coordinates avoid the wrapped-key/camera-origin coupling in UE.
#ifndef FALCOR_WORLD_CACHE
#define FALCOR_WORLD_CACHE
cbuffer WorldCacheCB
{
    uint gWCSize;
    float gWCDensity;
    uint gWCDownsample;
    uint gWCBounces;
    uint gWCHistory;
    uint gWCMaxAge;
    float gWCMinCell;
    float gWCMaxIntensity;
    float3 gWCCamera;
};
globallycoherent RWStructuredBuffer<uint> gWCState;
globallycoherent RWStructuredBuffer<int4> gWCKeys;
RWStructuredBuffer<float4> gWCLighting; // rgb: total diffuse outgoing radiance, w: history
RWStructuredBuffer<uint4> gWCAccumulation; // float32 RGB sums (CAS atomics), integer sample count
RWStructuredBuffer<uint> gWCAge;
RWStructuredBuffer<uint> gWCStats; // lookups, hits, failed insertions, occupied slots
static const uint WC_INVALID = 0xffffffffu;

uint wcHash(uint x)
{
    x ^= x >> 16; x *= 0x7feb352du; x ^= x >> 15; x *= 0x846ca68bu; return x ^ (x >> 16);
}
int4 wcKey(float3 p, float3 n)
{
    float distance = max(length(p - gWCCamera), gWCMinCell * gWCDensity);
    int level = int(clamp(floor(log2(distance / (gWCMinCell * gWCDensity))), 0.f, 24.f));
    float width = gWCMinCell * exp2(float(level));
    float3 a = abs(n);
    uint axis = a.x >= a.y && a.x >= a.z ? 0u : (a.y >= a.z ? 1u : 2u);
    uint face = axis * 2u + (n[axis] < 0.f ? 1u : 0u);
    return int4(int3(floor((p + float3(1e-5f)) / width)), level * 8 + int(face));
}
uint wcSlot(int4 key, bool insert)
{
    uint hash = wcHash(asuint(key.x) ^ wcHash(asuint(key.y)) ^ wcHash(asuint(key.z) + 1237u) ^ wcHash(asuint(key.w) + 4153u));
    // Never spin on a lock held by another lane. Contended insertions may retry
    // next frame; all reads of lighting refer to the previous completed update.
    for (uint step = 0; step < 4; ++step)
    {
        uint slot = (hash + step) & (gWCSize - 1u);
        uint state = gWCState[slot];
        if (state == 2u && all(gWCKeys[slot] == key)) return slot;
        if (state == 1u) return WC_INVALID;
        if (state == 0u && insert)
        {
            uint original;
            InterlockedCompareExchange(gWCState[slot], 0u, 1u, original);
            if (original == 0u)
            {
                gWCKeys[slot] = key;
                DeviceMemoryBarrier();
                InterlockedExchange(gWCState[slot], 2u);
                return slot;
            }
            if (original == 1u) return WC_INVALID;
            if (original == 2u && all(gWCKeys[slot] == key)) return slot;
        }
    }
    if (insert) InterlockedAdd(gWCStats[2], 1u);
    return WC_INVALID;
}
float3 wcLookup(float3 p, float3 n)
{
    InterlockedAdd(gWCStats[0], 1u);
    uint slot = wcSlot(wcKey(p, n), false);
    if (slot != WC_INVALID && gWCLighting[slot].w > 0.f)
    {
        InterlockedAdd(gWCStats[1], 1u);
        return gWCLighting[slot].rgb;
    }
    return float3(0.f);
}
void wcAtomicAdd(uint slot, uint component, float value)
{
    uint expected = gWCAccumulation[slot][component];
    for (;;)
    {
        uint original;
        uint desired = asuint(asfloat(expected) + value);
        InterlockedCompareExchange(gWCAccumulation[slot][component], expected, desired, original);
        if (original == expected) break;
        expected = original;
    }
}
void wcAccumulate(uint slot, float3 radiance, uint count)
{
    if (slot == WC_INVALID) return;
    if (!all(isfinite(radiance))) return;
    radiance = max(radiance, float3(0.f));
    float peak = max(radiance.x, max(radiance.y, radiance.z));
    if (gWCMaxIntensity > 0.f) radiance *= min(1.f, gWCMaxIntensity / max(peak, 1e-10f));
    wcAtomicAdd(slot, 0u, radiance.x);
    wcAtomicAdd(slot, 1u, radiance.y);
    wcAtomicAdd(slot, 2u, radiance.z);
    InterlockedAdd(gWCAccumulation[slot].w, count);
}
#endif
