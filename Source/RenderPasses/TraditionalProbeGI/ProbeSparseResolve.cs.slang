#include "Scene/SceneDefines.slangh"
#include "Utils/Math/MathConstants.slangh"
import Scene.Raytracing;
import Scene.Intersection;
import Utils.Math.MathHelpers;

cbuffer SparseCB
{
    uint2 gFrameDim;
    uint2 gSparseDim;
    uint gSparseStride;
    uint3 gGridCounts;
    float3 gGridMin;
    float3 gGridMax;
}
Texture2D<PackedHitInfo> gVBuffer;
Texture2D<float4> gViewW;
Texture2D<float4> gSparseIrradiance;
Texture2D<float4> gSparsePosition;
Texture2D<float4> gSparseNormal;
RWTexture2D<float4> gResolvedIrradiance;
#define is_valid(name) (is_valid_##name != 0)
#include "ProbeSurface.slang"
#define SPARSE_RESOLVE_ONLY
#include "ProbeSparse.slang"

[numthreads(8, 8, 1)]
void main(uint3 dispatchThreadID : SV_DispatchThreadID)
{
    uint2 pixel = dispatchThreadID.xy;
    if (any(pixel >= gFrameDim)) return;
    gResolvedIrradiance[pixel] = float4(0);
    HitInfo hit = HitInfo(gVBuffer[pixel]);
    if (!hit.isValid()) return;
    float3 direction = getPrimaryRayDir(pixel, gFrameDim, gScene.camera);
    ShadingData sd = loadShadingData(hit, gScene.camera.getPosition(), direction);
    float3 irradiance;
    if (reconstructSparse(pixel, sd.posW, sd.frame.N, sd.materialID, irradiance))
        gResolvedIrradiance[pixel] = float4(irradiance, 1);
}
