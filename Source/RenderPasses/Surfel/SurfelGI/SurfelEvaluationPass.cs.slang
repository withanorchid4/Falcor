import Scene.Scene;
import RenderPasses.Surfel.Random;
import RenderPasses.Surfel.HashUtils;
import RenderPasses.Surfel.SurfelGI.SurfelTypes;
import RenderPasses.Surfel.SurfelGI.SurfelUtils;
import RenderPasses.Surfel.SurfelGI.StaticParams;

struct SurfelQueryData { float4 positionRadius; float4 normalFrame; float4 irradiance; };
RWStructuredBuffer<SurfelQueryData> gQueryBuffer;
groupshared SurfelQueryData sharedSurfels[128];
groupshared uint sharedIndices[128];
groupshared uint cellMin;
groupshared uint cellMax;
groupshared uint cachedCount;

[numthreads(64,1,1)]
void packQuery(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= kTotalSurfelLimit) return;
    Surfel s = gSurfelBuffer[tid.x];
    SurfelQueryData q;
    q.positionRadius = float4(s.position,s.radius);
    q.normalFrame = float4(s.normal,float(gSurfelRecycleInfoBuffer[tid.x].frame));
    q.irradiance = float4(s.radiance,0);
    gQueryBuffer[tid.x] = q;
}

cbuffer CB
{
    bool gQueryMark;
    uint gFrameIndex;
    float gPlacementThreshold;
    float gRemovalThreshold;
    uint gBlendingDelay;
    uint gOverlayMode;
    float gVarianceSensitivity;
}

RWStructuredBuffer<Surfel> gSurfelBuffer;
RWStructuredBuffer<CellInfo> gCellInfoBuffer;
RWStructuredBuffer<uint> gCellToSurfelBuffer;
RWStructuredBuffer<SurfelRecycleInfo> gSurfelRecycleInfoBuffer;

RWByteAddressBuffer gSurfelRefCounter;

Texture2D<PackedHitInfo> gPackedHitInfo;
Texture2D<float2> gSurfelDepth;
RWTexture2D<float4> gOutput;

SamplerState gSurfelDepthSampler;

[numthreads(16, 16, 1)]
void csMain(
    uint3 dispatchThreadId: SV_DispatchThreadID,
    uint groupIndex: SV_GroupIndex,
    uint3 groupThreadID: SV_GroupThreadID,
    uint3 groupdId: SV_GroupID
)
{
    uint2 pixelPos = dispatchThreadId.xy;
    uint w,h; gOutput.GetDimensions(w,h);
    bool valid = all(pixelPos < uint2(w,h));
    VertexData v = {};
    uint flattenIndex = 0;
    if (valid) {
        HitInfo hitInfo = HitInfo(gPackedHitInfo[pixelPos]);
        valid = hitInfo.isValid();
        if (valid) {
            v = gScene.getVertexData(hitInfo.getTriangleHit());
            int3 cellPos = getCellPos(v.posW,gScene.camera.getPosition(),kCellUnit);
            valid = isCellValid(cellPos);
            if (valid) flattenIndex = getFlattenCellIndex(cellPos);
        }
    }
    CellInfo cellInfo = {};
    if (valid) cellInfo = gCellInfoBuffer[flattenIndex];
#if QUERY_SHARED
    if (groupIndex == 0) { cellMin = ~0u; cellMax = 0; cachedCount = 0; }
    GroupMemoryBarrierWithGroupSync();
    if (valid) { InterlockedMin(cellMin,flattenIndex); InterlockedMax(cellMax,flattenIndex); }
    GroupMemoryBarrierWithGroupSync();
    bool useShared = cellMin == cellMax && cellMin != ~0u;
    if (groupIndex == 0 && useShared) cachedCount = min(gCellInfoBuffer[cellMin].surfelCount,128u);
    GroupMemoryBarrierWithGroupSync();
    if (groupIndex < cachedCount) {
        uint idx = gCellToSurfelBuffer[gCellInfoBuffer[cellMin].cellToSurfelBufferOffset + groupIndex];
        sharedIndices[groupIndex] = idx;
        sharedSurfels[groupIndex] = gQueryBuffer[idx];
    }
    GroupMemoryBarrierWithGroupSync();
#endif
    if (!valid) return;
    float4 indirectLighting = float4(0.f);
    float coverage = 0.f;
    float varianceEx = 0.f;
    float rayCountEx = 0.f;
    uint refCount = 0;
    uint life = 0;

    float maxVariance = 0.f;

    for (uint i = 0; i < cellInfo.surfelCount; ++i)
    {
        uint surfelIndex;
        SurfelQueryData q;
#if QUERY_SHARED
        if (useShared && i < cachedCount) { surfelIndex = sharedIndices[i]; q = sharedSurfels[i]; }
        else
#endif
        {
            surfelIndex = gCellToSurfelBuffer[cellInfo.cellToSurfelBufferOffset+i];
#if QUERY_COMPACT
            q = gQueryBuffer[surfelIndex];
#else
            Surfel original = gSurfelBuffer[surfelIndex];
            q.positionRadius = float4(original.position,original.radius);
            q.normalFrame = float4(original.normal,float(gSurfelRecycleInfoBuffer[surfelIndex].frame));
            q.irradiance = float4(original.radiance,0);
#endif
        }
        Surfel surfel = Surfel(q.positionRadius.xyz,q.normalFrame.xyz,q.positionRadius.w);
        surfel.position = q.positionRadius.xyz; surfel.radius = q.positionRadius.w;
        surfel.normal = q.normalFrame.xyz; surfel.radiance = q.irradiance.xyz;
        float3 bias = v.posW - surfel.position;
        float dist2 = dot(bias, bias);

        if (dist2 < surfel.radius * surfel.radius)
        {
            float3 normal = normalize(surfel.normal);

            float dotN = dot(v.normalW, normal);
            if (dotN > 0)
            {
                float dist = sqrt(dist2);
                float contribution = 1.f;

                contribution *= saturate(dotN);
                contribution *= saturate(1 - dist / surfel.radius);
                contribution = smoothstep(0, 1, contribution);

                coverage += contribution;
                if (gQueryMark) InterlockedOr(gSurfelRecycleInfoBuffer[surfelIndex].status, 2u);

                #ifdef USE_SURFEL_DEPTH
                {
                    float2 uv = getSurfelDepthUV(surfelIndex, bias / max(dist, 1e-6f), normal);
                    float2 surfelDepth = gSurfelDepth.SampleLevel(gSurfelDepthSampler, uv, 0u);

                    float mean = surfelDepth.x;
                    float sqrMean = surfelDepth.y;

                    if (dist > mean)
                    {
                        float variance = max(0.f, sqrMean - pow(mean, 2));
                        contribution *= variance / (variance + pow(dist - mean, 2));
                    }
                }
                #else  // USE_SURFEL_DEPTH
                #endif // USE_SURFEL_DEPTH

                SurfelRecycleInfo surfelRecycleInfo = {};
                surfelRecycleInfo.frame = uint(q.normalFrame.w);
                if (gOverlayMode != 0) { surfel = gSurfelBuffer[surfelIndex]; surfelRecycleInfo = gSurfelRecycleInfoBuffer[surfelIndex]; }

                // Delay blending if not sufficient sample is accumulated.
                // Because samples are updated per frame, so do not use sample count directly.
                indirectLighting += float4(surfel.radiance, 1.f) * contribution * smoothstep(0, gBlendingDelay, surfelRecycleInfo.frame);

                varianceEx += length(surfel.msmeData.variance) * contribution;
                rayCountEx += surfel.rayCount * contribution;

                if (gOverlayMode != 0) refCount = max(refCount, gSurfelRefCounter.Load(4 * surfelIndex));
                life = max(life, surfelRecycleInfo.life);

                maxVariance = max(maxVariance, length(surfel.msmeData.variance));
            }
        }
    }

    if (indirectLighting.w > 0)
    {
        indirectLighting.xyz /= indirectLighting.w;
        indirectLighting.w = saturate(indirectLighting.w);

        varianceEx /= indirectLighting.w;
        rayCountEx /= indirectLighting.w;

        // Write texture by overlay mode.
        if (gOverlayMode == 0)
        {
            gOutput[pixelPos] = indirectLighting;
        }
        else if (gOverlayMode == 1)
        {
            gOutput[pixelPos] = float4(stepColor(maxVariance * gVarianceSensitivity, 0.8f, 0.5f), 1);
        }
        else if (gOverlayMode == 2)
        {
            gOutput[pixelPos] = float4(stepColor(rayCountEx, 48.f, 32.f), 1);
        }
        else if (gOverlayMode == 3)
        {
            gOutput[pixelPos] = float4(lerpColor(refCount / 256.f), 1);
        }
        else if (gOverlayMode == 4)
        {
            gOutput[pixelPos] = float4(step(life, 0u), step(1u, life), 0, 1);
        }
        else if (gOverlayMode == 5)
        {
            gOutput[pixelPos] = float4(lerpColor(smoothstep(gPlacementThreshold, gRemovalThreshold, coverage)), 1);
        }
    }
}
