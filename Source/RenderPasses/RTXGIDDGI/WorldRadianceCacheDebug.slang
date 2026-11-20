// Read-only visualization of the actual occupied WRC slots. Keep this shader
// independent of scene/material shaders; it neither traces nor updates lighting.
// Matches the 32-byte WrcKey layout in WorldRadianceCache.slang.
struct DebugKey
{
    uint key;
    uint level;
    int3 cell;
    uint valid;
    uint2 padding;
};
StructuredBuffer<DebugKey> gKeys;
StructuredBuffer<uint> gActiveSlots;
StructuredBuffer<uint> gActiveCounts;
RWByteAddressBuffer gDrawArgs;
Texture2D<float> gSurfaceDistance;

cbuffer DebugCB
{
    float4x4 gViewProj;
    float3 gCameraPosition;
    float gBaseCellWidth;
    uint gTableSize;
    uint gTypeCount;
    uint gBucket;
    uint gLodFilter;
    bool gXRay;
    float gOpacity;
}

[numthreads(1, 1, 1)]
void prepareDebug(uint3 id : SV_DispatchThreadID)
{
    if (id.x >= gTypeCount) return;
    // Twelve edges, two vertices per edge; one instance per occupied cell.
    gDrawArgs.Store4(id.x * 16u, uint4(24u, min(gActiveCounts[id.x], gTableSize), 0u, 0u));
}

struct VertexOut
{
    float4 position : SV_Position;
    float3 world : TEXCOORD0;
    nointerpolation float width : TEXCOORD1;
    nointerpolation float3 color : TEXCOORD2;
};

float3 lodColor(uint lod)
{
    if (lod == 1u) return float3(0.05f, 1.5f, 2.f);
    if (lod == 2u) return float3(0.1f, 2.f, 0.15f);
    if (lod == 4u) return float3(2.f, 1.5f, 0.05f);
    if (lod == 8u) return float3(2.f, 0.4f, 0.05f);
    if (lod == 16u) return float3(2.f, 0.1f, 0.8f);
    if (lod == 32u) return float3(1.f, 0.1f, 2.f);
    return float3(0.1f, 0.4f, 2.f);
}

VertexOut vsMain(uint vertexID : SV_VertexID, uint instanceID : SV_InstanceID)
{
    VertexOut result = (VertexOut)0;
    result.position = float4(2.f, 2.f, 0.f, 1.f);
    uint slot = gActiveSlots[gBucket * gTableSize + instanceID];
    if (slot >= gTableSize) return result;
    DebugKey key = gKeys[slot];
    uint lod = 1u << min(key.level, 31u);
    if (key.valid == 0u || (gLodFilter != 0u && lod != gLodFilter)) return result;
    uint edge = vertexID / 2u;
    uint axis = edge / 4u;
    uint side = edge % 4u;
    float3 corner = float3(0.f);
    corner[axis] = float(vertexID % 2u);
    corner[(axis + 1u) % 3u] = float(side & 1u);
    corner[(axis + 2u) % 3u] = float((side >> 1u) & 1u);
    result.width = gBaseCellWidth * float(lod);
    result.world = (float3(key.cell) + corner) * result.width;
    result.position = mul(gViewProj, float4(result.world, 1.f));
    result.color = lodColor(lod);
    return result;
}

float4 psMain(VertexOut input) : SV_Target0
{
    if (!gXRay)
    {
        float surfaceDistance = gSurfaceDistance.Load(int3(int2(input.position.xy), 0));
        if (length(input.world - gCameraPosition) > surfaceDistance + input.width * 0.02f) discard;
    }
    return float4(input.color, gOpacity);
}
