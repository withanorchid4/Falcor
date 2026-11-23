import Scene.Scene;
import RenderPasses.Surfel.Random;
import RenderPasses.Surfel.HashUtils;
import RenderPasses.Surfel.SurfelGI.SurfelTypes;
import RenderPasses.Surfel.SurfelGI.SurfelUtils;
import RenderPasses.Surfel.SurfelGI.StaticParams;

cbuffer CB
{
    uint2 gResolution;
    float gFOVy;
    uint gFrameIndex;
    float gChanceMultiply;
    uint gChancePower;
    float gPlacementThreshold;
    float gRemovalThreshold;
    uint gBlendingDelay;
    uint gOverlayMode;
    float gVarianceSensitivity;
}

RWStructuredBuffer<Surfel> gSurfelBuffer;
RWStructuredBuffer<uint4> gSurfelGeometryBuffer;
RWStructuredBuffer<uint> gSurfelFreeIndexBuffer;
RWStructuredBuffer<uint> gSurfelValidIndexBuffer;
RWStructuredBuffer<CellInfo> gCellInfoBuffer;
RWStructuredBuffer<uint> gCellToSurfelBuffer;
RWStructuredBuffer<SurfelRecycleInfo> gSurfelRecycleInfoBuffer;

RWByteAddressBuffer gSurfelRefCounter;
RWByteAddressBuffer gSurfelCounter;

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
    // One rotating candidate per tile. No barriers after divergent validity tests.
    RNG selector; selector.init(groupdId.xy, gFrameIndex);
    if (groupIndex != selector.next_uint(256)) return;
    uint groupShareMinCoverage = ~0u;
    uint groupShareMaxContribution = 0;
    if (dispatchThreadId.x >= gResolution.x || dispatchThreadId.y >= gResolution.y)
        return;

    uint2 tilePos = groupdId.xy;
    uint2 pixelPos = dispatchThreadId.xy;

    RNG randomState;
    randomState.init(pixelPos, gFrameIndex);

    HitInfo hitInfo = HitInfo(gPackedHitInfo[pixelPos]);
    if (!hitInfo.isValid())
        return;

    TriangleHit triangleHit = hitInfo.getTriangleHit();
    VertexData v = gScene.getVertexData(triangleHit);
    float4 curPosH = mul(gScene.camera.data.viewProjMatNoJitter, float4(v.posW, 1.f));
    float depth = curPosH.z / curPosH.w;

    int3 cellPos = getCellPos(v.posW, gScene.camera.getPosition(), kCellUnit);
    if (!isCellValid(cellPos))
        return;

    uint flattenIndex = getFlattenCellIndex(cellPos);
    CellInfo cellInfo = gCellInfoBuffer[flattenIndex];

    // Evaluate min coverage value and pixel position.
    // Also evaluate max contribution and surfel index (for handling over-coverage).
    // Also evalute weighted color output (indrect lighting).
    float4 indirectLighting = float4(0.f);
    {
        float coverage = 0.f;
        float varianceEx = 0.f;
        float rayCountEx = 0.f;
        uint refCount = 0;
        uint life = 0;

        float maxVariance = 0.f;
        float maxContribution = 0.f;
        uint maxContributionSurfelIndex = randomState.next_uint(cellInfo.surfelCount);

        for (uint i = 0; i < cellInfo.surfelCount; ++i)
        {
            uint surfelIndex = gCellToSurfelBuffer[cellInfo.cellToSurfelBufferOffset + i];
            Surfel surfel = gSurfelBuffer[surfelIndex];

            float3 bias = v.posW - surfel.position;
            float dist2 = dot(bias, bias);

            if (dist2 < surfel.radius * surfel.radius)
            {
                float3 normal = normalize(surfel.normal);

                float dotN = dot(v.normalW, normal);
                if (dotN > 0)
                {
                    const SurfelRecycleInfo surfelRecycleInfo = gSurfelRecycleInfoBuffer[surfelIndex];
                    bool isSleeping = surfelRecycleInfo.status & 0x0001;
                    bool lastSeen = surfelRecycleInfo.status & 0x0002;

                    if (!isSleeping)
                    {
                        float dist = sqrt(dist2);
                        float contribution = 1.f;

                        contribution *= saturate(dotN);
                        contribution *= saturate(1 - dist / surfel.radius);
                        contribution = smoothstep(0, 1, contribution);

                        coverage += contribution;

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

                        // Delay blending if not sufficient sample is accumulated.
                        // Because samples are updated per frame, so do not use sample count directly.
                        indirectLighting += float4(surfel.radiance, 1.f) * contribution * smoothstep(0, gBlendingDelay, surfelRecycleInfo.frame);

                        varianceEx += length(surfel.msmeData.variance) * contribution;
                        rayCountEx += surfel.rayCount * contribution;

                        refCount = max(refCount, gSurfelRefCounter.Load(4 * surfelIndex));
                        life = max(life, surfelRecycleInfo.life);

                        if (maxContribution < contribution)
                        {
                            maxContribution = contribution;
                            maxContributionSurfelIndex = i;
                        }

                        maxVariance = max(maxVariance, length(surfel.msmeData.variance));
                    }

                    if (!lastSeen)
                        InterlockedOr(gSurfelRecycleInfoBuffer[surfelIndex].status, 2u);
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

        uint coverageData = 0;
        coverageData |= ((f32tof16(coverage) & 0x0000FFFF) << 16);
        coverageData |= ((randomState.next_uint(255) & 0x000000FF) << 8);
        coverageData |= ((groupThreadID.x & 0x0000000F) << 4);
        coverageData |= ((groupThreadID.y & 0x0000000F) << 0);

        groupShareMinCoverage = coverageData;

        uint contributionData = 0;
        contributionData |= ((f32tof16(maxContribution) & 0x0000FFFF) << 16);
        contributionData |= ((maxContributionSurfelIndex & 0x0000FFFF) << 0);

        groupShareMaxContribution = contributionData;


    }

    uint coverageData = groupShareMinCoverage;
    float coverage = f16tof32((coverageData & 0xFFFF0000) >> 16);
    uint x = (coverageData & 0x000000F0) >> 4;
    uint y = (coverageData & 0x0000000F) >> 0;

    if (cellInfo.surfelCount < kPerCellSurfelLimit)
    {
        if (groupThreadID.x == x && groupThreadID.y == y)
        {
            // If seat for surfel in current cell avaliable and coverage is under threshold,
            // genearte new surfel probabilistically.
            if (coverage <= gPlacementThreshold)
            {
                const float chance = pow(depth, gChancePower);
                if (randomState.next_float() < chance * gChanceMultiply)
                {
                    // A failed allocation must not decrement the counter below zero:
                    // recycling in the next frame relies on it as a stack index.
                    int freeSurfelCount = asint(gSurfelCounter.Load((int)SurfelCounterOffset::FreeSurfel));
                    while (freeSurfelCount > 0)
                    {
                        uint previous;
                        gSurfelCounter.InterlockedCompareExchange((int)SurfelCounterOffset::FreeSurfel,
                            freeSurfelCount, freeSurfelCount - 1, previous);
                        if (previous == uint(freeSurfelCount)) break;
                        freeSurfelCount = asint(previous);
                    }

                    if (0 < freeSurfelCount && freeSurfelCount <= kTotalSurfelLimit)
                    {
                        uint validSurfelCount;
                        gSurfelCounter.InterlockedAdd((int)SurfelCounterOffset::ValidSurfel, 1, validSurfelCount);

                        if (validSurfelCount < kTotalSurfelLimit)
                        {
                            uint newIndex = gSurfelFreeIndexBuffer[freeSurfelCount - 1];

                            float varRadius = calcSurfelRadius(
                                distance(gScene.camera.getPosition(), v.posW),
                                gFOVy,
                                gResolution,
                                kSurfelTargetArea,
                                kCellUnit
                            );

                            Surfel newSurfel = Surfel(v.posW, v.normalW, varRadius);

                            newSurfel.radiance = indirectLighting.xyz;
                            newSurfel.msmeData.mean = indirectLighting.xyz;
                            newSurfel.msmeData.shortMean = indirectLighting.xyz;

                            gSurfelValidIndexBuffer[validSurfelCount] = newIndex;
                            gSurfelBuffer[newIndex] = newSurfel;
                            gSurfelRecycleInfoBuffer[newIndex] = { kMaxLife, 0u, 0u };
                            gSurfelGeometryBuffer[newIndex] = hitInfo.data;
                            gSurfelRefCounter.Store(4 * newIndex, 0);
                        }
                    }
                }
            }
        }
    }

}
