#include "RTXGIConfig.slang"
#include "ProbeCubemapCommon.slang"
#include "RTXGI/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl"
import Scene.Scene;
StructuredBuffer<DDGIVolumeDescGPUPacked> DDGIVolumes;
Texture2DArray<float4> gProbeData;
StructuredBuffer<float4> gMeshBounds;
RWByteAddressBuffer gArgs16;
RWByteAddressBuffer gArgs32;
RWByteAddressBuffer gCounts;
RWStructuredBuffer<uint> gViewMasks;
cbuffer CaptureCB
{
    uint gStart;
    uint gCount;
    uint gTotal;
    float gNear;
    float gFar;
    uint gInstances;
    bool gMultiview;
    bool gAcrossProbes;
    uint gTriangleDivisor;
}
bool visibleBox(float3 c, float3 e, uint face)
{
    float3 F = cubeForward(face), U = cubeUp(face), R = cross(F, U);
    if (dot(c, F) + dot(e, abs(F)) < gNear || dot(c, F) - dot(e, abs(F)) > gFar)
        return false;
    float3 n = F + R;
    if (dot(c, n) + dot(e, abs(n)) < 0)
        return false;
    n = F - R;
    if (dot(c, n) + dot(e, abs(n)) < 0)
        return false;
    n = F + U;
    if (dot(c, n) + dot(e, abs(n)) < 0)
        return false;
    n = F - U;
    return dot(c, n) + dot(e, abs(n)) >= 0;
}
[numthreads(64, 1, 1)] void main(uint3 tid : SV_DispatchThreadID) {
    uint inst = tid.x / 192, group = tid.x % 192;
    uint views = gMultiview ? 3 : 1, groupsPerProbe = 6 / views;
    uint slot = gAcrossProbes ? (group / 6) * 3 : group / groupsPerProbe,
         firstFace = gAcrossProbes ? group % 6 : (group % groupsPerProbe) * views;
    if (inst >= gInstances || slot >= gCount)
        return;
    GeometryInstanceID id = {inst};
    let instance = gScene.getGeometryInstance(id);
    // Curves/SDFs/displaced meshes index other tables; match Scene::rasterize().
    if (instance.getType() != GeometryType::TriangleMesh)
        return;
    let mesh = gScene.meshes[instance.geometryID];
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    float3 origin = DDGIGetProbeWorldPosition(DDGIGetProbeCoords((gStart + slot) % gTotal, volume), volume, gProbeData);
    bool dynamic = instance.isDynamic() || mesh.isSkinned() || mesh.isAnimated();
    float4x4 M = gScene.getWorldMatrix(id);
    float3 center = mul(M, float4(gMeshBounds[instance.geometryID * 2].xyz, 1)).xyz;
    float3 e = mul(abs((float3x3)M), gMeshBounds[instance.geometryID * 2 + 1].xyz);
    uint mask = 0;
    for (uint v = 0; v < views; v++)
    {
        uint viewSlot = slot + (gAcrossProbes ? v : 0);
        if (viewSlot >= gCount)
            continue;
        float3 viewOrigin = gAcrossProbes
                                ? DDGIGetProbeWorldPosition(DDGIGetProbeCoords((gStart + viewSlot) % gTotal, volume), volume, gProbeData)
                                : origin;
        if (dynamic || visibleBox(center - viewOrigin, e, firstFace + (gAcrossProbes ? 0 : v)))
            mask |= 1u << v;
    }
    if (mask == 0)
        return;
    uint encoded = inst * 192 + group;
    if (gMultiview)
        gViewMasks[encoded] = mask;
    if (gTriangleDivisor == 0) return;
    uint address;
    bool small = mesh.use16BitIndices();
    // Separate indirect lists let the command list mask unused hardware views,
    // rather than broadcasting all views and clipping them in the vertex shader.
    uint bucket = gMultiview ? mask - 1 : 0;
    uint counter = gMultiview ? ((small ? 0 : 7) + bucket) * 4 : (small ? 0 : 4);
    gCounts.InterlockedAdd(counter, 1, address);
    address = (bucket * gInstances * 192 + address) * 20;
    uint indexCount = gTriangleDivisor == 1 ? mesh.indexCount : (mesh.indexCount / 3 / gTriangleDivisor) * 3;
    uint4 args = uint4(indexCount, 1, mesh.ibOffset * (small ? 2 : 1), mesh.vbOffset);
    if (small)
    {
        gArgs16.Store4(address, args);
        gArgs16.Store(address + 16, encoded);
    }
    else
    {
        gArgs32.Store4(address, args);
        gArgs32.Store(address + 16, encoded);
    }
}
