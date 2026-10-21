/**
 * Traditional diffuse SH probe baking and runtime sampling.
 * Material, intersection and path-scattering helpers below are derived from
 * MinimalPathTracer. The ray-generation stage either traces probe paths or
 * shades camera-visible surfaces from a completed, persistent probe volume.
 */
#include "Scene/SceneDefines.slangh"
#include "Utils/Math/MathConstants.slangh"

import Scene.Raytracing;
import Scene.Intersection;
import Utils.Math.MathHelpers;
import Utils.Geometry.GeometryHelpers;
import Utils.Sampling.SampleGenerator;
import Rendering.Lights.LightHelpers;
import ProbeSH;
import ProbeDistance;

cbuffer ProbeCB
{
    uint3 gGridCounts;
    float3 gGridMin;
    float3 gGridMax;
    uint gSampleStart;
    uint gSampleBatch;
    uint gSampleTotal;
    bool gBake;
    bool gBakeDistance;
    bool gBakeDistanceRays;
    uint gDistanceTexelOffset;
    bool gReady;
    bool gProbeOnly;
    bool gPreviewUnbaked;
    float gIntensity;
    float gNormalBias;
    float gViewBias;
    uint gDistanceResolution;
    uint2 gDistanceAtlasSize;
    float gDistanceMax;
    float gDistanceHitBias;
    bool gDistanceBilinear;
    bool gDistanceSmooth;
    bool gUseVisibility;
    bool gRayTracedVisibility;
    bool gUseNormalWeight;
    float gVisibilityPower;
    float gVarianceBase;
    bool gDDGIWeights;
    bool gWickedWeights;
    uint gSelectedProbe;
    bool gDebugEnabled;
    bool gHasBakedData;
    uint gDebugView;
    bool gInspect;
    bool gPick;
    uint2 gPickPixel;
    uint2 gFrameDim;
    bool gSparseBuild;
    bool gSparseEnabled;
    uint gSparseStride;
    uint2 gSparseDim;
}
cbuffer WickedCB
{
    bool gWickedActive;
    bool gWickedBake;
    uint gWickedRayCount;
    float gWickedNormalBias;
    float gWickedSmoothBackface;
}
Texture2D<float2> gWickedMoments;
SamplerState gWickedSampler;
RWStructuredBuffer<float4> gWickedRays;
RWTexture2D<float4> gSparseIrradiance;
RWTexture2D<float4> gSparsePosition;
RWTexture2D<float4> gSparseNormal;
Texture2D<float4> gResolvedIrradiance;
RWStructuredBuffer<float4> gProbeSH;
// Per probe: rejected attempts, unrecovered samples, first rejected sample + 1, reason flags.
RWStructuredBuffer<uint4> gBakeHealth;
RWTexture2D<float4> gDistanceMoments;
RWStructuredBuffer<float4> gDistanceRays;
RWTexture2D<float4> gProbeLighting;
RWStructuredBuffer<float4> gDebugData;
RWTexture2D<float> gDebugDistance;

cbuffer CB
{
    uint gFrameCount;    // Frame count since scene was loaded.
    uint gPRNGDimension; // First available PRNG dimension.
}

// Inputs
Texture2D<PackedHitInfo> gVBuffer;
Texture2D<float4> gViewW; // Optional

// Outputs
RWTexture2D<float4> gOutputColor;
RWTexture2D<float4> gSamplingInfo;

// Static configuration based on defines set from the host.
#define is_valid(name) (is_valid_##name != 0)
static const uint kMaxBounces = MAX_BOUNCES;
static const bool kComputeDirect = COMPUTE_DIRECT;
static const bool kUseImportanceSampling = USE_IMPORTANCE_SAMPLING;
static const bool kUseAnalyticLights = USE_ANALYTIC_LIGHTS;
static const bool kUseEmissiveLights = USE_EMISSIVE_LIGHTS;
static const bool kUseEnvLight = USE_ENV_LIGHT;
static const bool kUseEnvBackground = USE_ENV_BACKGROUND;
static const float3 kDefaultBackgroundColor = float3(0, 0, 0);
static const float kRayTMax = FLT_MAX;

/**
 * Payload for shadow ray.
 */
struct ShadowRayData
{
    bool visible;
};

/**
 * Payload for scatter ray (up to 80B).
 */
struct ScatterRayData
{
    float3 radiance;  ///< Accumulated outgoing radiance from path.
    bool terminated;  ///< Set to true when path is terminated.
    float3 thp;       ///< Current path throughput. This is updated at each path vertex.
    uint pathLength;  ///< Path length in number of path segments (0 at origin, 1 at first secondary hit, etc.). Max 2^31.
    float3 origin;    ///< Next path segment origin.
    float3 direction; ///< Next path segment direction.
    float firstHitDistance;
    bool distanceOnly;

    SampleGenerator sg; ///< Per-ray state for the sample generator (up to 16B).

    /**
     * Initializes ray payload with default parameters.
     */
    __init(SampleGenerator sg)
    {
        this.terminated = false;
        this.pathLength = 0;
        this.radiance = float3(0, 0, 0);
        this.thp = float3(1, 1, 1);
        this.origin = float3(0, 0, 0);
        this.direction = float3(0, 0, 0);
        this.firstHitDistance = gDistanceMax;
        this.distanceOnly = false;
        this.sg = sg;
    }
};

/**
 * Setup ShadingData based on loaded vertex/material attributes for a hit point.
 * @param[in] hit Hit information.
 * @param[in] rayOrigin Ray origin.
 * @param[in] rayDir Normalized ray direction.
 * @return ShadingData struct.
 */
#include "ProbeSurface.slang"

/**
 * Traces a shadow ray towards a light source.
 * @param[in] origin Ray origin for the shadow ray.
 * @param[in] dir Direction from shading point towards the light source (normalized).
 * @param[in] distance Distance to the light source.
 * @return True if light is visible, false otherwise.
 */
bool traceShadowRay(float3 origin, float3 dir, float distance)
{
    RayDesc ray;
    ray.Origin = origin;
    ray.Direction = dir;
    ray.TMin = 0.f;
    ray.TMax = distance;

    ShadowRayData rayData;
    rayData.visible = false; // Set to true by miss shader if ray is not terminated before
    TraceRay(
        gScene.rtAccel,
        RAY_FLAG_ACCEPT_FIRST_HIT_AND_END_SEARCH,
        0xff /* instanceInclusionMask */,
        1 /* hitIdx */,
        rayTypeCount,
        1 /* missIdx */,
        ray,
        rayData
    );

    return rayData.visible;
}

/**
 * Traces a scatter ray based on ray parameters stored in the ray payload.
 * @param[in] rayData Describes the ray parameters. The struct is modified based on the result.
 */
void traceScatterRay(inout ScatterRayData rayData)
{
    RayDesc ray;
    ray.Origin = rayData.origin;
    ray.Direction = rayData.direction;
    ray.TMin = 0.f;
    ray.TMax = kRayTMax;

    uint rayFlags = 0; // TODO: Set cull mode from the app
    TraceRay(gScene.rtAccel, rayFlags, 0xff /* instanceInclusionMask */, 0 /* hitIdx */, rayTypeCount, 0 /* missIdx */, ray, rayData);
}

float probeRayEpsilon()
{
    float3 spacing = (gGridMax - gGridMin) / float3(gGridCounts - 1);
    return max(1e-6f, min(spacing.x, min(spacing.y, spacing.z)) * 1e-4f);
}

// Nearest hit, not the first hit encountered in BVH traversal. A negative value means MISS.
// Uses the same geometry hit groups and alpha testing as probe baking, without material shading.
float traceProbeDistance(float3 probe, float3 point)
{
    float3 delta = point - probe;
    float distance = length(delta);
    if (distance <= 1e-8f) return -1.f;
    ScatterRayData payload = ScatterRayData(SampleGenerator(uint2(0), 0));
    payload.distanceOnly = true;
    payload.firstHitDistance = -1.f;
    RayDesc ray;
    ray.Origin = probe;
    ray.Direction = delta / distance;
    ray.TMin = 0.f;
    ray.TMax = max(gDistanceMax, distance + probeRayEpsilon());
    TraceRay(gScene.rtAccel, gWickedActive ? (RAY_FLAG_FORCE_OPAQUE | RAY_FLAG_SKIP_PROCEDURAL_PRIMITIVES) : 0, 0xff, 0, rayTypeCount, 0, ray, payload);
    return payload.firstHitDistance;
}

bool probeHitVisible(float hitDistance, float pointDistance)
{
    return hitDistance < 0.f || hitDistance >= pointDistance - probeRayEpsilon();
}

float traceProbeVisibility(float3 probe, float3 point)
{
    float3 delta = point - probe;
    float distance = length(delta);
    if (distance <= probeRayEpsilon()) return 1.f;
    // Only a boolean is needed here, so early-out on any accepted segment hit is correct.
    if (gWickedActive)
    {
        RayDesc ray;
        ray.Origin = probe; ray.Direction = delta / distance; ray.TMin = 0.f; ray.TMax = distance - probeRayEpsilon();
        ShadowRayData payload; payload.visible = false;
        TraceRay(gScene.rtAccel, RAY_FLAG_FORCE_OPAQUE | RAY_FLAG_SKIP_PROCEDURAL_PRIMITIVES | RAY_FLAG_ACCEPT_FIRST_HIT_AND_END_SEARCH,
            0xff, 1, rayTypeCount, 1, ray, payload);
        return payload.visible ? 1.f : 0.f;
    }
    return traceShadowRay(probe, delta / distance, distance - probeRayEpsilon()) ? 1.f : 0.f;
}

/**
 * Evaluates the direct illumination from analytic lights.
 * This function samples Falcor's light list uniformly with one shadow ray.
 * @param[in] sd Shading data.
 * @param[in] mi Material instance.
 * @param[in,out] sg SampleGenerator object.
 * @return Outgoing radiance in view direction.
 */
float3 evalDirectAnalytic(const ShadingData sd, const IMaterialInstance mi, inout SampleGenerator sg)
{
    const uint lightCount = gScene.getLightCount();
    if (lightCount == 0)
        return float3(0.f);

    // Pick one of the analytic light sources randomly with equal probability.
    const uint lightIndex = min(uint(sampleNext1D(sg) * lightCount), lightCount - 1);
    float invPdf = lightCount; // Light selection pdf = 1.0 / lightCount.

    // Sample local light source.
    AnalyticLightSample ls;
    if (!sampleLight(sd.posW, gScene.getLight(lightIndex), sg, ls))
        return float3(0.f);

    // Reject sample if not in the hemisphere of a BSDF lobe.
    const uint lobeTypes = mi.getLobeTypes(sd);
    const bool hasReflection = lobeTypes & uint(LobeType::Reflection);
    const bool hasTransmission = lobeTypes & uint(LobeType::Transmission);
    float NdotL = dot(sd.getOrientedFaceNormal(), ls.dir);
    if ((NdotL <= kMinCosTheta && !hasTransmission) || (NdotL >= -kMinCosTheta && !hasReflection))
        return float3(0.f);

    // Get origin with offset applied in direction of the geometry normal to avoid self-intersection.
    const float3 origin = computeRayOrigin(sd.posW, dot(sd.faceN, ls.dir) >= 0.f ? sd.faceN : -sd.faceN);

    // Test visibility by tracing a shadow ray.
    bool V = traceShadowRay(origin, ls.dir, ls.distance);
    if (!V)
        return float3(0.f);

    // Evaluate contribution.
    return mi.eval(sd, ls.dir, sg) * ls.Li * invPdf;
}

/**
 * Generate a new scatter ray or terminate.
 * @param[in] sd Shading data.
 * @param[in] mi Material instance.
 * @param[in] isCurveHit True if on curve hit.
 * @param[in] rayOrigin Ray origin for the new ray.
 * @param[in,out] rayData Ray payload.
 * @return True if the path continues.
 */
bool generateScatterRay(const ShadingData sd, const IMaterialInstance mi, bool isCurveHit, float3 rayOrigin, inout ScatterRayData rayData)
{
    // Sample material.
    BSDFSample bsdfSample = {};
    if (mi.sample(sd, rayData.sg, bsdfSample, kUseImportanceSampling))
    {
        rayData.origin = rayOrigin;
        if (!isCurveHit && bsdfSample.isLobe(LobeType::Transmission))
        {
            rayData.origin = sd.computeRayOrigin(false);
        }
        rayData.direction = bsdfSample.wo;
        rayData.thp *= bsdfSample.weight;
        return any(rayData.thp > 0.f);
    }

    return false;
}

/**
 * Process a hit.
 * Loads the shading data, samples analytic lights and samples a new scatter ray.
 * Terminates the path if maximum number of bounces is reached.
 * @param[in] hit Hit info.
 * @param[in,out] rayData Ray payload.
 *
 */
void handleHit(const HitInfo hit, inout ScatterRayData rayData)
{
    if (rayData.distanceOnly)
    {
        rayData.firstHitDistance = RayTCurrent();
        rayData.terminated = true;
        return;
    }
    if (rayData.pathLength == 0) rayData.firstHitDistance = min(RayTCurrent(), gDistanceMax);
    const bool isCurveHit = hit.getType() == HitType::Curve;

    // Load shading data.
    ShadingData sd = loadShadingData(hit, rayData.origin, rayData.direction);

    // Create material instance.
    let lod = ExplicitLodTextureSampler(0.f);
    let mi = gScene.materials.getMaterialInstance(sd, lod);

    // Add emitted light.
    if (kUseEmissiveLights && (kComputeDirect || rayData.pathLength > 0))
    {
        rayData.radiance += rayData.thp * mi.getProperties(sd).emission;
    }

    // Check whether to terminate based on max depth.
    if (rayData.pathLength >= kMaxBounces)
    {
        rayData.terminated = true;
        return;
    }

    // Compute ray origin for new rays spawned from the hit.
    float3 rayOrigin;
    if (isCurveHit)
    {
        // For curves, we set the new origin at the sphere center.
        rayOrigin = sd.posW - sd.curveRadius * sd.frame.N;
    }
    else
    {
        rayOrigin = sd.computeRayOrigin();
    }

    // Add contribution of direct light from analytic lights.
    if (kUseAnalyticLights)
    {
        float3 Lr = evalDirectAnalytic(sd, mi, rayData.sg);
        rayData.radiance += rayData.thp * Lr;
    }

    // Generate scatter ray for the next path segment.
    // The raygen shader will continue the path based on the returned payload.
    if (!generateScatterRay(sd, mi, isCurveHit, rayOrigin, rayData))
    {
        rayData.terminated = true;
        return;
    }

    rayData.pathLength++;
}

//
// Shader entry points for miss shaders.
//

[shader("miss")]
void scatterMiss(inout ScatterRayData rayData)
{
    // Ray missed the scene. Mark the ray as terminated.
    rayData.terminated = true;
    if (rayData.distanceOnly) return;

    // Add contribution from distant light (env map) in this direction.
    if (kUseEnvLight && (kComputeDirect || rayData.pathLength > 0))
    {
        float3 Le = gScene.envMap.eval(WorldRayDirection());
        rayData.radiance += rayData.thp * Le;
    }
}

[shader("miss")]
void shadowMiss(inout ShadowRayData rayData)
{
    // The miss shader is executed if the ray misses all geometry. Mark as visible.
    rayData.visible = true;
}

//
// Shader entry points for TriangleMesh hit groups.
//

[shader("anyhit")]
void scatterTriangleMeshAnyHit(inout ScatterRayData rayData, BuiltInTriangleIntersectionAttributes attribs)
{
    // Alpha test for non-opaque geometry.
    GeometryInstanceID instanceID = getGeometryInstanceID();
    VertexData v = getVertexData(instanceID, PrimitiveIndex(), attribs);
    const uint materialID = gScene.getMaterialID(instanceID);
    if (gScene.materials.alphaTest(v, materialID, 0.f))
        IgnoreHit();
}

[shader("closesthit")]
void scatterTriangleMeshClosestHit(inout ScatterRayData rayData, BuiltInTriangleIntersectionAttributes attribs)
{
    TriangleHit triangleHit;
    triangleHit.instanceID = getGeometryInstanceID();
    triangleHit.primitiveIndex = PrimitiveIndex();
    triangleHit.barycentrics = attribs.barycentrics;
    handleHit(HitInfo(triangleHit), rayData);
    if (gWickedBake && rayData.distanceOnly && HitKind() == HIT_KIND_TRIANGLE_BACK_FACE)
        rayData.firstHitDistance *= 0.9f;
}

[shader("anyhit")]
void shadowTriangleMeshAnyHit(inout ShadowRayData rayData, BuiltInTriangleIntersectionAttributes attribs)
{
    // Alpha test for non-opaque geometry.
    GeometryInstanceID instanceID = getGeometryInstanceID();
    VertexData v = getVertexData(instanceID, PrimitiveIndex(), attribs);
    const uint materialID = gScene.getMaterialID(instanceID);
    if (gScene.materials.alphaTest(v, materialID, 0.f))
        IgnoreHit();
}

//
// Shader entry points for DisplacedTriangleMesh hit groups.
//

[shader("intersection")]
void displacedTriangleMeshIntersection()
{
    const Ray ray = Ray(WorldRayOrigin(), WorldRayDirection(), RayTMin(), RayTCurrent());
    DisplacedTriangleMeshIntersector::Attribs attribs;
    float t;
    if (DisplacedTriangleMeshIntersector::intersect(ray, getGeometryInstanceID(), PrimitiveIndex(), attribs, t))
    {
        ReportHit(t, 0, attribs);
    }
}

[shader("closesthit")]
void scatterDisplacedTriangleMeshClosestHit(inout ScatterRayData rayData, DisplacedTriangleMeshIntersector::Attribs attribs)
{
    DisplacedTriangleHit displacedTriangleHit;
    displacedTriangleHit.instanceID = getGeometryInstanceID();
    displacedTriangleHit.primitiveIndex = PrimitiveIndex();
    displacedTriangleHit.barycentrics = attribs.barycentrics;
    displacedTriangleHit.displacement = attribs.displacement;
    handleHit(HitInfo(displacedTriangleHit), rayData);
}

//
// Shader entry points for Curve hit groups.
//

[shader("intersection")]
void curveIntersection()
{
    const Ray ray = Ray(WorldRayOrigin(), WorldRayDirection(), RayTMin(), RayTCurrent());
    CurveIntersector::Attribs attribs;
    float t;
    if (CurveIntersector::intersect(ray, getGeometryInstanceID(), PrimitiveIndex(), attribs, t))
    {
        ReportHit(t, 0, attribs);
    }
}

[shader("closesthit")]
void scatterCurveClosestHit(inout ScatterRayData rayData, CurveIntersector::Attribs attribs)
{
    CurveHit curveHit;
    curveHit.instanceID = getGeometryInstanceID();
    curveHit.primitiveIndex = PrimitiveIndex();
    curveHit.barycentrics = attribs.barycentrics;
    handleHit(HitInfo(curveHit), rayData);
}

//
// Shader entry points for SDFGrid hit groups.
//

[shader("intersection")]
void sdfGridIntersection()
{
    const Ray ray = Ray(WorldRayOrigin(), WorldRayDirection(), RayTMin(), RayTCurrent());
    SDFGridHitData sdfGridHitData;
    float t;
    if (SDFGridIntersector::intersect(ray, getGeometryInstanceID(), PrimitiveIndex(), sdfGridHitData, t))
    {
        ReportHit(t, 0, sdfGridHitData);
    }
}

[shader("closesthit")]
void scatterSdfGridClosestHit(inout ScatterRayData rayData, SDFGridHitData sdfGridHitData)
{
    SDFGridHit sdfGridHit;
    sdfGridHit.instanceID = getGeometryInstanceID();
    sdfGridHit.hitData = sdfGridHitData;
    handleHit(HitInfo(sdfGridHit), rayData);
}

//
// Shader entry point for ray generation shader.
//

uint flattenProbe(uint3 p)
{
    return p.x + gGridCounts.x * (p.y + gGridCounts.y * p.z);
}

void bakeProbe(uint index)
{
    uint3 p = uint3(index % gGridCounts.x, (index / gGridCounts.x) % gGridCounts.y,
                    index / (gGridCounts.x * gGridCounts.y));
    float3 origin = lerp(gGridMin, gGridMax, float3(p) / float3(gGridCounts - 1));
    float3 coefficients[9];
    for (uint k = 0; k < 9; ++k) coefficients[k] = gProbeSH[index * 9 + k].xyz;
    uint4 health = gBakeHealth[index];
    for (uint s = 0; s < gSampleBatch; ++s)
    {
        bool accepted = false;
        for (uint attempt = 0; attempt <= 8 && !accepted; ++attempt)
        {
            // Attempt 0 is identical to the original estimator. Recovery seeds are deterministic.
            SampleGenerator sg = SampleGenerator(uint2(index, gSampleStart + s), attempt);
            float2 u = sampleNext2D(sg);
            float z = 1.f - 2.f * u.x;
            float r = sqrt(max(0.f, 1.f - z * z));
            float phi = 6.28318530718f * u.y;
            float3 direction = float3(r * cos(phi), r * sin(phi), z);
            ScatterRayData payload = ScatterRayData(sg);
            payload.origin = origin;
            payload.direction = direction;
            uint reason = 0;
            for (uint depth = 0; depth <= kMaxBounces && !payload.terminated; ++depth)
            {
                if (!all(isfinite(payload.origin))) reason |= 4;
                if (!all(isfinite(payload.direction)) || dot(payload.direction, payload.direction) < 1e-12f) reason |= 8;
                if (reason != 0) break;
                traceScatterRay(payload);
                if (!all(isfinite(payload.radiance))) reason |= 1;
                if (!all(isfinite(payload.thp))) reason |= 2;
                if (reason != 0) break;
            }
            float3 candidate[9];
            if (reason == 0)
                for (uint k = 0; k < 9; ++k)
                {
                    candidate[k] = coefficients[k] + payload.radiance * (12.5663706144f * probeSH(k, direction));
                    if (!all(isfinite(candidate[k]))) reason |= 16;
                }
            if (reason == 0)
            {
                for (uint k = 0; k < 9; ++k) coefficients[k] = candidate[k];
                accepted = true;
            }
            else
            {
                if (health.x == 0) { health.z = gSampleStart + s + 1; health.w = reason; }
                ++health.x;
            }
        }
        if (!accepted) ++health.y;
    }
    // This invocation exclusively owns this probe; no atomics are needed.
    for (uint k = 0; k < 9; ++k) gProbeSH[index * 9 + k] = float4(coefficients[k], 0.f);
    gBakeHealth[index] = health;
}

#include "WickedProbeVisibility.slang"

uint3 probeCell(float3 position, float3 normal, out float3 t, out float3 biasedPosition, out bool clamped)
{
    if (gWickedActive) return wickedCell(position, normal, t, biasedPosition, clamped);
    float3 spacing = (gGridMax - gGridMin) / float3(gGridCounts - 1);
    float minSpacing = min(spacing.x, min(spacing.y, spacing.z));
    // Compute both components at P. Do not normalize the combined bias vector.
    float3 bias = normal * (gNormalBias * minSpacing);
    if (gViewBias > 0.f)
    {
        float3 toCamera = gScene.camera.getPosition() - position;
        float cameraDistance = length(toCamera);
        float3 viewDirection = cameraDistance > 1e-8f ? toCamera / cameraDistance : float3(0.f);
        bias += viewDirection * (gViewBias * minSpacing);
    }
    position += bias;
    biasedPosition = position;
    float3 raw = (position - gGridMin) / spacing;
    clamped = any(raw < 0.f) || any(raw > float3(gGridCounts - 1));
    float3 q = clamp(raw, float3(0), float3(gGridCounts - 1));
    uint3 cell = min(uint3(floor(q)), gGridCounts - 2);
    t = q - float3(cell);
    return cell;
}

uint2 distanceTexel(float3 direction)
{
    return min(uint2(saturate(probeOctEncode(direction)) * float(gDistanceResolution)), uint2(gDistanceResolution - 1));
}

uint2 distancePixel(uint index, uint2 texel)
{
    uint tileSize = gDistanceResolution + 2;
    uint columns = gDistanceAtlasSize.x / tileSize;
    uint2 tile = uint2(index % columns, index / columns);
    return tile * tileSize + 1 + texel;
}

float2 distanceMoments(uint index, float3 direction)
{
    if (gWickedActive) return wickedMoments(index, direction) / float2(gDistanceMax, gDistanceMax * gDistanceMax);
    if (!gDistanceBilinear)
        return gDistanceMoments[distancePixel(index, distanceTexel(direction))].xy;
    // Bilinear interpolation of the two moments, with folded octahedral edges.
    // Old caches have unused padding: never sample padding or another probe's tile.
    float2 p = saturate(probeOctEncode(direction)) * float(gDistanceResolution) - 0.5f;
    int2 base = int2(floor(p));
    float2 t = frac(p);
    // Convex moment interpolation, with zero slope at texel centers. Same four reads.
    if (gDistanceSmooth) t = t * t * (3.f - 2.f * t);
    int n = int(gDistanceResolution);
    float2 m00 = gDistanceMoments[distancePixel(index, uint2(probeOctWrap(base, n)))].xy;
    float2 m10 = gDistanceMoments[distancePixel(index, uint2(probeOctWrap(base + int2(1,0), n)))].xy;
    float2 m01 = gDistanceMoments[distancePixel(index, uint2(probeOctWrap(base + int2(0,1), n)))].xy;
    float2 m11 = gDistanceMoments[distancePixel(index, uint2(probeOctWrap(base + int2(1,1), n)))].xy;
    return lerp(lerp(m00, m10, t.x), lerp(m01, m11, t.x), t.y);
}

void bakeDistanceRays(uint index)
{
    uint3 grid = uint3(index % gGridCounts.x, (index / gGridCounts.x) % gGridCounts.y,
        index / (gGridCounts.x * gGridCounts.y));
    float3 origin = lerp(gGridMin, gGridMax, float3(grid) / float3(gGridCounts - 1));
    for (uint s = 0; s < gSampleBatch; ++s)
    {
        float3 direction = probeDistanceRayDirection(index, gSampleStart + s);
        float hit = traceProbeDistance(origin, origin + direction * gDistanceMax);
        gDistanceRays[index * 16 + s] = float4(direction, hit < 0.f ? 1.f : saturate((hit - gDistanceHitBias) / gDistanceMax));
    }
}

void bakeDistanceTexel(uint task)
{
    uint linear = gDistanceTexelOffset + task;
    uint area = gDistanceResolution * gDistanceResolution;
    uint index = linear / area;
    uint local = linear % area;
    uint2 texel = uint2(local % gDistanceResolution, local / gDistanceResolution);
    uint3 grid = uint3(index % gGridCounts.x, (index / gGridCounts.x) % gGridCounts.y,
        index / (gGridCounts.x * gGridCounts.y));
    float3 origin = lerp(gGridMin, gGridMax, float3(grid) / float3(gGridCounts - 1));
    uint2 pixel = distancePixel(index, texel);
    float2 sum = gDistanceMoments[pixel].xy * float(gSampleStart);
    for (uint s = 0; s < gSampleBatch; ++s)
    {
        SampleGenerator sg = SampleGenerator(uint2(linear, gSampleStart + s), 0);
        // Uniform within this UV square; no samples from other texels.
        float2 jitter = clamp(sampleNext2D(sg), float2(1e-5f), float2(1.f - 1e-5f));
        float3 direction = probeOctDecode((float2(texel) + jitter) / float(gDistanceResolution));
        float hit = traceProbeDistance(origin, origin + direction * gDistanceMax);
        float d = hit < 0.f ? 1.f : saturate((hit - gDistanceHitBias) / gDistanceMax);
        sum += float2(d, d * d);
    }
    uint count = gSampleStart + gSampleBatch;
    gDistanceMoments[pixel] = float4(sum / float(count), float(count), 0.f);
}

// Static adaptation of DDGI moment weighting; ray visibility remains an exact reference.
bool ddgiWeightingActive()
{
    return gDDGIWeights && gUseVisibility && gHasBakedData && !gRayTracedVisibility;
}

float rawMomentVisibility(float query, float2 moments)
{
    if (!gDDGIWeights && !gWickedActive) return probeChebyshev(query, moments, gVarianceBase, gVisibilityPower);
    // This branch also covers the zero-variance, zero-distance-difference case.
    if (query <= moments.x) return 1.f;
    float difference = query - moments.x;
    float variance = abs(moments.y - moments.x * moments.x);
    float probability = variance / (variance + difference * difference);
    return probability * probability * probability;
}

float probeWeightDenominator(float total)
{
    // DDGI may intentionally produce tiny weights: normalize their actual sum.
    return max(total, (gWickedActive || ddgiWeightingActive()) ? 1e-20f : 1e-4f);
}

// Unnormalized weights are shared by final shading, support view and point inspection.
float cornerWeight(float3 position, float3 normal, float3 biased, uint3 cell, float3 t, uint corner,
    out float trilinear, out float visibility, out float4 distanceInfo)
{
    if (gWickedActive) return wickedCornerWeight(position, normal, biased, cell, t, corner, trilinear, visibility, distanceInfo);
    uint3 offset = uint3(corner & 1, (corner >> 1) & 1, (corner >> 2) & 1);
    float3 factors = lerp(1.f - t, t, float3(offset));
    if (ddgiWeightingActive() && !gWickedWeights) factors = max(factors, float3(0.001f));
    trilinear = factors.x * factors.y * factors.z;
    float3 probePosition = lerp(gGridMin, gGridMax, float3(cell + offset) / float3(gGridCounts - 1));
    float3 delta = biased - probePosition;
    float distance = length(delta);
    float3 dir = distance > 1e-8f ? delta / distance : float3(0, 0, 1);
    float2 moments = gHasBakedData ? distanceMoments(flattenProbe(cell + offset), dir) : float2(1);
    visibility = rawMomentVisibility(distance / gDistanceMax, moments);
    if (ddgiWeightingActive() && !gWickedWeights) visibility = max(visibility, 0.05f);
    if (gUseVisibility && gRayTracedVisibility && gHasBakedData)
        visibility = trilinear > 0.f ? traceProbeVisibility(probePosition, biased) : 0.f;
    float3 toProbe = probePosition - position;
    float cosine = dot(normal, toProbe / max(length(toProbe), 1e-8f));
    float wrap = saturate(cosine * 0.5f + 0.5f);
    float normalWeight = gUseNormalWeight ? wrap * wrap + 0.2f : 1.f;
    float rawVariance = moments.y - moments.x * moments.x;
    distanceInfo = float4(moments.x * gDistanceMax,
        (gDDGIWeights ? abs(rawVariance) : max(0.f, rawVariance)) * gDistanceMax * gDistanceMax, distance, normalWeight);
    float support = normalWeight * visibility;
    if (ddgiWeightingActive())
    {
        support = max(support, gWickedWeights ? 0.01f : 1e-6f);
        float compression = min(support / 0.2f, 1.f);
        support *= compression * compression;
    }
    return trilinear * (gUseVisibility && gHasBakedData ? support : 1.f);
}

float3 sampleProbeIrradiance(float3 position, float3 normal)
{
    float3 t, biasedPosition;
    bool clamped;
    uint3 cell = probeCell(position, normal, t, biasedPosition, clamped);
    float3 irradiance = float3(0);
    float totalWeight = 0.f;
    for (uint corner = 0; corner < 8; ++corner)
    {
        uint3 offset = uint3(corner & 1, (corner >> 1) & 1, (corner >> 2) & 1);
        float tri, visibility;
        float4 info;
        float weight = cornerWeight(position, normal, biasedPosition, cell, t, corner, tri, visibility, info);
        totalWeight += weight;
        uint index = flattenProbe(cell + offset);
        for (uint k = 0; k < 9; ++k)
            irradiance += weight * gProbeSH[index * 9 + k].xyz *
                (probeSH(k, normal) * probeCosineKernel(k) / float(gSampleTotal));
    }
    return max(irradiance / probeWeightDenominator(totalWeight), float3(0));
}

#include "ProbeSparse.slang"

// One invocation, only on demand. Inspection never feeds back into production lighting.
void inspectSurface()
{
    if (gPick)
    {
        for (uint i = 0; i < 52; ++i) gDebugData[i] = float4(0);
        HitInfo hit = HitInfo(gVBuffer[gPickPixel]);
        if (!hit.isValid()) return;
        float3 direction = getPrimaryRayDir(gPickPixel, gFrameDim, gScene.camera);
        ShadingData sd = loadShadingData(hit, gScene.camera.getPosition(), direction);
        gDebugData[0] = float4(sd.posW, 1.f);
        gDebugData[1] = float4(sd.frame.N, 0.f);
    }
    if (gDebugData[0].w == 0.f) return;
    float3 position = gDebugData[0].xyz, normal = gDebugData[1].xyz;
    float3 t, biased;
    bool clamped;
    uint3 cell = probeCell(position, normal, t, biased, clamped);
    gDebugData[1] = float4(normal, clamped ? 1.f : 0.f);
    gDebugData[2] = float4(biased, 1.f);
    float3 total = float3(0);
    float totalWeight = 0.f;
    for (uint j = 0; j < 8; ++j)
    {
        float tri, visibility;
        float4 info;
        totalWeight += cornerWeight(position, normal, biased, cell, t, j, tri, visibility, info);
    }
    for (uint corner = 0; corner < 8; ++corner)
    {
        uint3 offset = uint3(corner & 1, (corner >> 1) & 1, (corner >> 2) & 1);
        float tri, visibility;
        float4 info;
        float weight = cornerWeight(position, normal, biased, cell, t, corner, tri, visibility, info) / probeWeightDenominator(totalWeight);
        uint index = flattenProbe(cell + offset);
        float3 probePosition = lerp(gGridMin, gGridMax, float3(cell + offset) / float3(gGridCounts - 1));
        float queryHit = traceProbeDistance(probePosition, biased);
        float surfaceHit = traceProbeDistance(probePosition, position);
        float3 queryDelta = biased - probePosition;
        float3 surfaceDelta = position - probePosition;
        float surfaceDistance = length(surfaceDelta);
        bool visible = probeHitVisible(queryHit, info.z);
        float2 queryMoments = gHasBakedData ? distanceMoments(index, info.z > 1e-8f ? queryDelta / info.z : float3(0,0,1)) : float2(1);
        float momentVisibility = gWickedActive ? wickedVisibility(info.z, wickedMoments(index,
            info.z > 1e-8f ? queryDelta / info.z : float3(0,0,1))) : rawMomentVisibility(info.z / gDistanceMax, queryMoments);
        float2 surfaceMoments = gHasBakedData ? distanceMoments(index,
            surfaceDistance > 1e-8f ? surfaceDelta / surfaceDistance : float3(0,0,1)) : float2(1);
        float appliedVisibility = !gUseVisibility || !gHasBakedData ? 1.f : visibility;
        float3 contribution = float3(0);
        if (gHasBakedData)
            for (uint k = 0; k < 9; ++k)
                contribution += weight * gProbeSH[index * 9 + k].xyz *
                    (probeSH(k, normal) * probeCosineKernel(k) / float(gSampleTotal));
        total += contribution;
        gDebugData[4 + 3 * corner] = float4(probePosition, float(index));
        gDebugData[5 + 3 * corner] = float4(weight, visible ? 1.f : 0.f, tri, momentVisibility);
        gDebugData[6 + 3 * corner] = float4(contribution, 0.f);
        gDebugData[28 + corner] = info;
        gDebugData[36 + corner] = float4(queryHit, surfaceHit, surfaceDistance, visible ? 1.f : 0.f);
        uint2 queryTexel = distanceTexel(info.z > 1e-8f ? queryDelta / info.z : float3(0,0,1));
        gDebugData[44 + corner] = float4(surfaceMoments.x * gDistanceMax,
            max(0.f, surfaceMoments.y - surfaceMoments.x * surfaceMoments.x) * gDistanceMax * gDistanceMax,
            float(queryTexel.x + queryTexel.y * gDistanceResolution), appliedVisibility);
    }
    gDebugData[3] = float4(max(total, float3(0)), 1.f);
}

[shader("raygeneration")]
void rayGen()
{
    uint2 pixel = DispatchRaysIndex().xy;
    if (gWickedBake) { bakeWickedRays(DispatchRaysIndex().x); return; }
    if (gBakeDistanceRays) { bakeDistanceRays(pixel.x); return; }
    if (gBakeDistance) { bakeDistanceTexel(pixel.x); return; }
    if (gBake) { bakeProbe(pixel.x); return; }
    if (gInspect) { inspectSurface(); return; }
#if SPARSE_RUNTIME
    if (gSparseBuild) { buildSparseSample(pixel); return; }
#endif
    float3 samplingInfo = float3(0);
#if is_valid(gSamplingInfo)
    gSamplingInfo[pixel] = float4(0, 0, 0, 1);
#endif
    if (gDebugEnabled && gDebugView >= 7 && gDebugView <= 8)
    {
        float2 uv = (float2(pixel) + 0.5f) / float2(gFrameDim);
        float2 moments = distanceMoments(gSelectedProbe, probeOctDecode(uv));
        float value = gDebugView == 7 ? moments.x : sqrt(max(0.f, moments.y - moments.x * moments.x));
        gOutputColor[pixel] = float4(gHasBakedData ? float3(value) : float3(0), 1);
        gProbeLighting[pixel] = float4(0, 0, 0, 1);
        return;
    }
    float3 direction = getPrimaryRayDir(pixel, gFrameDim, gScene.camera);
    HitInfo hit = HitInfo(gVBuffer[pixel]);
    float3 color = float3(0), probeColor = float3(0);
    float surfaceDistance = FLT_MAX;
    if (hit.isValid())
    {
        ShadingData sd = loadShadingData(hit, gScene.camera.getPosition(), direction);
        surfaceDistance = length(sd.posW - gScene.camera.getPosition());
        let mi = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f));
        let properties = mi.getProperties(sd);
        SampleGenerator sg = SampleGenerator(pixel, gFrameCount);
        color = properties.emission;
        if (kUseAnalyticLights) color += evalDirectAnalytic(sd, mi, sg);
        if (gReady)
        {
            float3 irradiance;
            bool reused = false;
#if SPARSE_RUNTIME
            if (gSparseEnabled)
            {
                float4 cached = gResolvedIrradiance[pixel];
                irradiance = cached.xyz;
                reused = cached.w > 0.f;
            }
#endif
            if (!reused) irradiance = sampleProbeIrradiance(sd.posW, sd.frame.N);
            samplingInfo = float3(reused ? 1.f : 0.f, reused ? 0.f : 1.f, 1.f);
            probeColor = properties.diffuseReflectionAlbedo * irradiance * (gIntensity / 3.1415926536f);
        }
        color += probeColor;
        if (gPreviewUnbaked)
        {
            // Only a geometry preview while waiting/baking, never part of the GI result.
            float shade = 0.25f + 0.75f * max(0.f, dot(sd.frame.N, normalize(float3(0.3f, 0.8f, 0.5f))));
            color = properties.emission + properties.diffuseReflectionAlbedo * shade;
        }
        if (gDebugEnabled && gDebugView != 0)
        {
            if (gDebugView >= 9)
            {
                float3 t, Q; bool clamped;
                probeCell(sd.posW, sd.frame.N, t, Q, clamped);
                uint3 coord = uint3(gSelectedProbe % gGridCounts.x, (gSelectedProbe / gGridCounts.x) % gGridCounts.y,
                    gSelectedProbe / (gGridCounts.x * gGridCounts.y));
                float3 probe = lerp(gGridMin, gGridMax, float3(coord) / float3(gGridCounts - 1));
                float3 delta = Q - probe;
                float2 moments = distanceMoments(gSelectedProbe, delta / max(length(delta), 1e-8f));
                float mu2 = moments.x * moments.x * gDistanceMax * gDistanceMax;
                float m2 = moments.y * gDistanceMax * gDistanceMax;
                color = float3(gDebugView == 9 ? m2 : gDebugView == 10 ? mu2 : abs(m2 - mu2));
            }
            else if (gDebugView == 1) color = gHasBakedData ? sampleProbeIrradiance(sd.posW, sd.frame.N) : float3(0);
            else if (gDebugView == 2) color = properties.diffuseReflectionAlbedo;
            else if (gDebugView == 3) color = sd.frame.N * 0.5f + 0.5f;
            else
            {
                float3 t, biased;
                bool clamped;
                uint3 cell = probeCell(sd.posW, sd.frame.N, t, biased, clamped);
                if (gDebugView == 4) color = frac(float3(cell) * float3(0.618034f, 0.414214f, 0.732051f) + 0.15f);
                else if (gDebugView == 5) color = clamped ? float3(1, 0, 1) : float3(0.04f);
                else
                {
                    float support = 0.f;
                    for (uint corner = 0; corner < 8; ++corner)
                    {
                        float tri, visibility;
                        float4 info;
                        cornerWeight(sd.posW, sd.frame.N, biased, cell, t, corner, tri, visibility, info);
                        support += tri * visibility;
                    }
                    color = gHasBakedData ? float3(support) : float3(0);
                }
            }
        }
    }
    else if (kUseEnvBackground) color = gScene.envMap.eval(direction);
    gProbeLighting[pixel] = float4(probeColor, 1.f);
    gOutputColor[pixel] = float4(gProbeOnly && !(gDebugEnabled && gDebugView != 0) ? probeColor : color, 1.f);
    if (gDebugEnabled) gDebugDistance[pixel] = surfaceDistance;
#if is_valid(gSamplingInfo)
    gSamplingInfo[pixel] = float4(samplingInfo, 1.f);
#endif
}
