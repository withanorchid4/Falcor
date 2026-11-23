#include "RTXGIConfig.slang"
#include "RTXGI/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl"
StructuredBuffer<DDGIVolumeDescGPUPacked> DDGIVolumes;
Texture2DArray<float4> gProbeData;
RWStructuredBuffer<float4> gPositions;
cbuffer PositionCB { uint gStart; uint gCount; uint gTotal; }
[numthreads(64, 1, 1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= gCount) return;
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    int3 coords = DDGIGetProbeCoords((gStart + tid.x) % gTotal, volume);
    gPositions[tid.x] = float4(DDGIGetProbeWorldPosition(coords, volume, gProbeData), 0.f);
}
