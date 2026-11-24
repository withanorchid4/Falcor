/***************************************************************************
 # Copyright (c) 2015-24, NVIDIA CORPORATION. All rights reserved.
 #
 # Redistribution and use in source and binary forms, with or without
 # modification, are permitted provided that the following conditions are met:
 # * Redistributions of source code must retain the above copyright notice,
 #   this list of conditions and the following disclaimer.
 # * Redistributions in binary form must reproduce the above copyright notice,
 #   this list of conditions and the following disclaimer in the documentation
 #   and/or other materials provided with the distribution.
 # * Neither the name of NVIDIA CORPORATION nor the names of its contributors
 #   may be used to endorse or promote products derived from this software
 #   without specific prior written permission.
 #
 # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS "AS IS" AND ANY EXPRESS
 # OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
 # OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
 # IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY
 # DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 # (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 # LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 # ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 # (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
 # THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 ***************************************************************************/

// Falcor scene/material bridge for NVIDIA RTXGI-DDGI with optional generated query adaptations.
// Intersection, alpha testing and analytic-light sampling follow MinimalPathTracer.
// Only triangle meshes are supported by this first integration. Glass is treated
// as a geometric boundary; optional final gather adds one reflection segment, not transmission.
// The SDK owns ray directions, encoding, relocation/classification, and querying.

#include "Scene/SceneDefines.slangh"
#include "Utils/Math/MathConstants.slangh"
#include "RTXGIConfig.slang"
#include "RTXGI/rtxgi-sdk/shaders/ddgi/IrradianceTetrahedral.hlsl"

#ifndef RASTER_PROBE_CAPTURE
#define RASTER_PROBE_CAPTURE 0
#endif
#if RASTER_PROBE_CAPTURE
#include "ProbeCubemapCommon.slang"
Texture2DArray<uint4> gRasterHits;
cbuffer RasterCB { uint gRasterOffset; uint gRasterSize; }
#endif
import Rendering.Materials.IsotropicGGX;
import Scene.Raytracing;
import Scene.Intersection;
import Scene.Material.ShadingUtils;
#ifndef DDGI_INLINE_SHADOW
#define DDGI_INLINE_SHADOW 0
#endif
#if DDGI_INLINE_SHADOW
import Scene.RaytracingInline;
#endif
import Utils.Math.MathHelpers;
import Utils.Geometry.GeometryHelpers;
import Utils.Sampling.SampleGenerator;
import Rendering.Lights.LightHelpers;
import Rendering.Lights.EmissiveUniformSampler;
import Rendering.Lights.EmissiveLightSamplerInterface;
import Rendering.Lights.EnvMapSampler;

#ifndef SHARC_CACHE
#define SHARC_CACHE 0
#endif
#if SHARC_CACHE
#include "SharcCache.slang"
#endif
#ifndef LUMEN_WORLD_CACHE
#define LUMEN_WORLD_CACHE 0
#endif
// The WRC compute library includes this file without the camera-pass defines.
#ifndef RESTIR_GATHER
#define RESTIR_GATHER 0
#endif
#ifndef SPLIT_HALF_GATHER
#define SPLIT_HALF_GATHER 0
#endif
#if LUMEN_WORLD_CACHE
#include "LumenWorldCache.slang"
#endif
// idTech 8 style final-gather caches (DDGI + final gather only). The host sets
// these defines; WRC shader libraries include this file with both off.
#ifndef FINAL_GATHER_WRC
#define FINAL_GATHER_WRC 0
#endif
#ifndef FINAL_GATHER_SCREEN_CACHE
#define FINAL_GATHER_SCREEN_CACHE 0
#endif
#if FINAL_GATHER_WRC && !defined(FALCOR_DDGI_WORLD_RADIANCE_CACHE)
#define WRC_FINAL_GATHER_ONLY 1
#include "WorldRadianceCache.slang"
#define FG_USE_WRC 1
#else
#define FG_USE_WRC 0
#endif
#define FG_USE_CACHES (FG_USE_WRC || FINAL_GATHER_SCREEN_CACHE)
cbuffer PerFrameCB
{
    uint gFrameCount;
    uint2 gFrameDim;
    uint gProbeBatchStart;
    uint gProbeBatchCount;
    bool gEnableGI;
    bool gFinalGather;
    bool gAdjustPrimaryShadingNormals;
    bool gHalfResolutionGather;
    uint2 gGatherOffset;
    uint gRestirHistoryLength;
    uint gRestirMaxAge;
    bool gRestirTemporalCellMapping;
    uint2 gRestirDim;
    uint2 gRestirPreviousOffset;
    float4x4 gRestirPreviousViewProj;
    bool gRestirHistoryValid;
    uint gRestirSpatialSamples;
    bool gRestirBiasCorrection;
    uint gRestirIntegrateSamples;
    float gRestirSpatialRadius;
    uint gRestirSpatialPassIndex;
    float gRestirIntegrateRadius;
    bool gRestirFullResolution;
    bool gGatherDiffuse;
    bool gGatherSpecular;
    bool gIndirectOnly;
    bool gUseRTXDI;
    bool gShowWrcCells;
    bool gHistoryValid;
    float gIntensity; // Display scaling only; recursive transport stays physical.
    float gProbeRadius; // World-space radius of the optional diagnostic spheres.
    // Screen-space radiance cache: previous frame's lit gather pixels.
    float4x4 gScreenCachePrevViewProj;
    float3 gScreenCachePrevCamera;
    bool gScreenCacheValid;     // False after resets, resizes and mode changes.
    uint2 gScreenCachePrevOffset;
    float gScreenCacheTolerance; // Relative position tolerance (fraction of camera distance).
}

#if FINAL_GATHER_SCREEN_CACHE
Texture2D<float4> gScreenCacheColor;    // rgb: outgoing radiance toward the previous camera
Texture2D<float4> gScreenCachePos;      // xyz: world position, w: 1 if valid
RWTexture2D<float4> gScreenCacheColorOut;
RWTexture2D<float4> gScreenCachePosOut;
#endif
#if FG_USE_CACHES
// 0 gather hits, 1 screen-cache hits, 2 WRC hits, 3 shaded fallbacks.
RWStructuredBuffer<uint> gFgCacheCounters;
#endif

StructuredBuffer<DDGIVolumeDescGPUPacked> DDGIVolumes;
RWTexture2DArray<float4> gRayData;
Texture2DArray<float4> gIrradiance;
Texture2DArray<float4> gDistance;
Texture2DArray<float4> gProbeData;
SamplerState gProbeSampler;
#if USE_ENV_LIGHT
ParameterBlock<EnvMapSampler> gEnvMapSampler;
#endif
#if USE_ENV_LIGHT || USE_ENV_BACKGROUND
Texture2D<float4> gSafeEnvironment;
#endif
// Non-finite input rejection counters: material/surface, direct/sample,
// historical irradiance, and combined radiance. The host exposes these counts.
RWStructuredBuffer<uint> gDiagnostics;
Texture2D<PackedHitInfo> gVBuffer;
Texture2D<float4> gViewW;
#if HAS_DIRECT_LIGHTING
Texture2D<float4> gDirectLighting;
#endif
RWTexture2D<float4> gOutputColor;
RWTexture2D<float> gWrcDebugDepth;
#if OUTPUT_INDIRECT
RWTexture2D<float4> gOutputIndirect;
#endif

#if OUTPUT_GATHER_DIFFUSE
RWTexture2D<float4> gOutputGatherDiffuse;
#endif
#if OUTPUT_GATHER_SPECULAR
RWTexture2D<float4> gOutputGatherSpecular;
#endif

#if OUTPUT_DIFFUSERADIANCEHITDIST
RWTexture2D<float4> gDiffuseRadianceHitDist;
#endif
#if OUTPUT_SPECULARRADIANCEHITDIST
RWTexture2D<float4> gSpecularRadianceHitDist;
#endif
#if OUTPUT_DIFFUSEREFLECTANCE
RWTexture2D<float4> gDiffuseReflectance;
#endif
#if OUTPUT_SPECULARREFLECTANCE
RWTexture2D<float4> gSpecularReflectance;
#endif
#if OUTPUT_UNFILTEREDCOLOR
RWTexture2D<float4> gUnfilteredColor;
#endif

// Host binds two ray types: probe=0, visibility=1. The payload is at most
// 24 bytes even when Falcor uses an uncompressed 128-bit PackedHitInfo.
// All lighting is evaluated in raygen, so trace recursion depth 1 suffices.
struct ProbeRayPayload
{
    PackedHitInfo hit;
    float hitT;
    uint backFace;
};

struct ShadowRayPayload
{
    bool visible;
};

void rejectNonFinite(uint category)
{
    InterlockedAdd(gDiagnostics[category], 1u);
}

float3 finiteRadiance(float3 value, uint category)
{
    if (!all(isfinite(value)))
    {
        rejectNonFinite(category);
    }
    // Keep valid channels when a source HDR texel contains a single Inf/NaN.
    return float3(isfinite(value.x) ? max(value.x, 0.f) : 0.f,
        isfinite(value.y) ? max(value.y, 0.f) : 0.f,
        isfinite(value.z) ? max(value.z, 0.f) : 0.f);
}

#if USE_ENV_LIGHT || USE_ENV_BACKGROUND
float3 evaluateSafeEnvironment(float3 direction)
{
    // Use the same sanitized texture that built the importance distribution.
    // Cleaning after filtering the source HDR would lose valid neighboring texels.
    float3 radiance = gSafeEnvironment.SampleLevel(
        gScene.envMap.envSampler, gScene.envMap.worldToUv(direction), 0.f).rgb;
    return finiteRadiance(radiance * gScene.envMap.getIntensity(), 1u);
}
#endif

// Match the SDK test harness: sky radiance enters the volume on probe misses.
// Falcor uses its directional HDR environment instead of a constant sky color.
float3 evaluateProbeMiss(float3 direction)
{
#if USE_ENV_LIGHT
    return evaluateSafeEnvironment(direction);
#else
    return float3(0.f);
#endif
}

bool validSurface(ShadingData sd)
{
    bool valid = all(isfinite(sd.posW)) && all(isfinite(sd.faceN)) && all(isfinite(sd.frame.N)) &&
        dot(sd.faceN, sd.faceN) > 1e-12f && dot(sd.frame.N, sd.frame.N) > 1e-12f;
    if (!valid) rejectNonFinite(0u);
    return valid;
}

DDGIVolumeResources getDDGIResources()
{
    DDGIVolumeResources resources;
    resources.probeIrradiance = gIrradiance;
    resources.probeDistance = gDistance;
    resources.probeData = gProbeData;
    resources.bilinearSampler = gProbeSampler;
    return resources;
}

ShadingData loadTriangleSurface(HitInfo hit, float3 incidentDirection)
{
    const TriangleHit triangleHit = hit.getTriangleHit();
    VertexData vertex = gScene.getVertexData(triangleHit);
    uint materialID = gScene.getMaterialID(triangleHit.instanceID);
    return gScene.materials.prepareShadingData(vertex, materialID, -incidentDirection);
}

float3 primaryRayDirection(uint2 pixel)
{
#if is_valid_gViewW
    return -gViewW[pixel].xyz;
#else
    return gScene.camera.computeRayPinhole(pixel, gFrameDim).dir;
#endif
}

bool traceShadow(float3 origin, float3 direction, float distance)
{
    if (!all(isfinite(origin)) || !all(isfinite(direction)) || !isfinite(distance))
    {
        rejectNonFinite(1u);
        return false;
    }
    if (distance <= 0.f) return false;
#if DDGI_INLINE_SHADOW
    SceneRayQuery<1> rayQuery;
    return rayQuery.traceVisibilityRay(Ray(origin, direction, 0.f, distance));
#else
    RayDesc ray;
    ray.Origin = origin;
    ray.Direction = direction;
    ray.TMin = 0.f;
    ray.TMax = distance;
    ShadowRayPayload payload;
    payload.visible = false;
    TraceRay(gScene.rtAccel, RAY_FLAG_ACCEPT_FIRST_HIT_AND_END_SEARCH | RAY_FLAG_SKIP_CLOSEST_HIT_SHADER,
        0xff, 1, rayTypeCount, 1, ray, payload);
    return payload.visible;
#endif
}

// Material setup applies normal maps and orientation to its own shading frame;
// sd.frame is the untextured vertex frame. Keep the Lambert cache model while
// using the same reflection hemisphere checks as Falcor's material instances.
bool validDiffuseReflection(ShadingData sd, BSDFProperties properties, float3 direction)
{
    bool validTangent;
    ShadingFrame sf = ShadingFrame::createSafe(properties.guideNormal, sd.tangentW, validTangent);
    return isValidHemisphereReflection(sd, sf, sf.toLocal(sd.V), sf.toLocal(direction), direction);
}

bool sampleDiffuseReflection(ShadingData sd, BSDFProperties properties, inout SampleGenerator sg, out float3 direction)
{
    // Preserve the existing cosine sampling distribution and random-number count.
    float3 n = properties.guideNormal;
    float2 u = sampleNext2D(sg);
    float3 t = normalize(cross(abs(n.z) < .999f ? float3(0, 0, 1) : float3(0, 1, 0), n));
    direction = t * (sqrt(u.x) * cos(2.f * M_PI * u.y)) + cross(n, t) * (sqrt(u.x) * sin(2.f * M_PI * u.y)) + n * sqrt(1.f - u.x);
    return dot(direction, sd.getOrientedFaceNormal()) > 0.f && validDiffuseReflection(sd, properties, direction);
}

float3 evaluateBRDFCosine(ShadingData sd, IMaterialInstance material, float3 direction, bool diffuseOnly, inout SampleGenerator sg)
{
    if (dot(sd.getOrientedFaceNormal(), direction) <= kMinCosTheta) return float3(0.f);
    if (diffuseOnly)
    {
        let properties = material.getProperties(sd);
        if (!validDiffuseReflection(sd, properties, direction)) return float3(0.f);
        float3 albedo = finiteRadiance(properties.diffuseReflectionAlbedo, 0u);
        return albedo * (max(0.f, dot(properties.guideNormal, direction)) / M_PI);
    }
    return finiteRadiance(material.eval(sd, direction, sg), 0u);
}

// The probe captures diffuse outgoing radiance; its recursive term must not
// contain a view-dependent specular lobe. At camera surfaces analytic direct
// illumination can evaluate the complete material BRDF, as in MinimalPathTracer.
float3 evaluateAnalyticDirect(ShadingData sd, IMaterialInstance material, bool diffuseOnly, inout SampleGenerator sg)
{
#if USE_ANALYTIC_LIGHTS
    uint lightCount = gScene.getLightCount();
    if (lightCount == 0) return float3(0.f);
    uint lightIndex = min(uint(sampleNext1D(sg) * lightCount), lightCount - 1);
    AnalyticLightSample light;
    if (!sampleLight(sd.posW, gScene.getLight(lightIndex), sg, light)) return float3(0.f);
    if (dot(sd.getOrientedFaceNormal(), light.dir) <= kMinCosTheta) return float3(0.f);
    float3 origin = computeRayOrigin(sd.posW, dot(sd.faceN, light.dir) >= 0.f ? sd.faceN : -sd.faceN);
    if (!traceShadow(origin, light.dir, light.distance)) return float3(0.f);
    float3 brdfCosine = evaluateBRDFCosine(sd, material, light.dir, diffuseOnly, sg);
    return finiteRadiance(brdfCosine * light.Li * float(lightCount), 1u);
#else
    return float3(0.f);
#endif
}

float3 evaluateEmissiveDirect(ShadingData sd, IMaterialInstance material, bool diffuseOnly, inout SampleGenerator sg)
{
#if USE_EMISSIVE_LIGHTS
    EmissiveUniformSampler emissiveSampler = {};
    TriangleLightSample light;
    if (!emissiveSampler.sampleLight(sd.posW, sd.getOrientedFaceNormal(), true, sg, light)) return float3(0.f);
    light.Le = finiteRadiance(light.Le, 1u);
    // Falcor explicitly allows +infinity for an area-light PDF at the grazing
    // limit. Its finite-radiance contribution is zero, not a corrupt sample.
    if (isinf(light.pdf) && light.pdf > 0.f) return float3(0.f);
    if (!isfinite(light.pdf) || !all(isfinite(light.dir)))
    {
        rejectNonFinite(1u);
        return float3(0.f);
    }
    if (light.pdf <= 0.f || dot(sd.getOrientedFaceNormal(), light.dir) <= kMinCosTheta) return float3(0.f);
    // Match PathTracer: offset BOTH endpoints using their geometric normals.
    // The segment ends on the light's emitting side instead of intersecting it.
    float3 lightPosition = computeRayOrigin(light.posW, light.normalW);
    float3 origin = computeRayOrigin(sd.posW, dot(sd.faceN, lightPosition - sd.posW) >= 0.f ? sd.faceN : -sd.faceN);
    float3 toLight = lightPosition - origin;
    float distance = length(toLight);
    if (!(distance > 0.f) || !isfinite(distance)) return float3(0.f);
    if (!traceShadow(origin, toLight / distance, distance)) return float3(0.f);
    float3 brdfCosine = evaluateBRDFCosine(sd, material, light.dir, diffuseOnly, sg);
    return finiteRadiance(brdfCosine * (light.Le / light.pdf), 1u);
#else
    return float3(0.f);
#endif
}

// Match PathTracer's primary-hit policy, including the GBuffer UI toggle.
// Probe and secondary hit materials intentionally keep their existing policy.
uint primaryMaterialHints()
{
    return gAdjustPrimaryShadingNormals ? (uint)MaterialInstanceHints::AdjustShadingNormal : 0u;
}

float3 evaluateEnvironmentDirect(ShadingData sd, IMaterialInstance material, bool diffuseOnly, inout SampleGenerator sg, uint materialHints = 0u)
{
#if USE_ENV_LIGHT
    // Diffuse sky lighting is supplied by DDGI, including at probe hit points.
    // Keep only the camera's specular environment response in the fallback path.
    if (diffuseOnly || (material.getLobeTypes(sd) & (uint)LobeType::SpecularReflection) == 0) return float3(0.f);
    EnvMapSample light;
    if (!gEnvMapSampler.sample(sampleNext2D(sg), light)) return float3(0.f);
    if (!isfinite(light.pdf) || !all(isfinite(light.dir)))
    {
        rejectNonFinite(1u);
        return float3(0.f);
    }
    if (light.pdf <= 0.f || dot(sd.getOrientedFaceNormal(), light.dir) <= kMinCosTheta) return float3(0.f);
    light.Le = evaluateSafeEnvironment(light.dir);
    float3 origin = computeRayOrigin(sd.posW, dot(sd.faceN, light.dir) >= 0.f ? sd.faceN : -sd.faceN);
    if (!traceShadow(origin, light.dir, FLT_MAX)) return float3(0.f);
    sd.mtl.setActiveLobes((uint)LobeType::SpecularReflection);
    let specularMaterial = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f), materialHints);
    float3 brdfCosine = evaluateBRDFCosine(sd, specularMaterial, light.dir, false, sg);
    return finiteRadiance(brdfCosine * (light.Le / light.pdf), 1u);
#else
    return float3(0.f);
#endif
}

float3 evaluateDirect(ShadingData sd, IMaterialInstance material, bool diffuseOnly, inout SampleGenerator sg, uint materialHints = 0u)
{
    // One sample per light category; diffuse environment lighting comes from DDGI.
    float3 radiance = evaluateAnalyticDirect(sd, material, diffuseOnly, sg);
    radiance += evaluateEmissiveDirect(sd, material, diffuseOnly, sg);
    radiance += evaluateEnvironmentDirect(sd, material, diffuseOnly, sg, materialHints);
    return finiteRadiance(radiance, 1u);
}

float3 queryIrradiance(float3 position, float3 normal, float3 incidentDirection, DDGIVolumeDescGPU volume)
{
    float blend = DDGIGetVolumeBlendWeight(position, volume);
    if (blend <= 0.f) return float3(0.f);
    float3 bias = DDGIGetSurfaceBias(normal, incidentDirection, volume);
    return finiteRadiance(blend * DDGIGetVolumeIrradiance(position, bias, normal, volume, getDDGIResources()), 2u);
}

// Dispatch dimensions follow the SDK sample: rays/probe, probes/plane, planes.
// All reads below use the previous completed volume. The host must finish this
// dispatch and its UAV barrier before running any SDK blending/update kernels.
[shader("raygeneration")]
void traceProbes()
{
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    uint3 launch = DispatchRaysIndex();
    int rayIndex = int(launch.x);
    int probeCount = volume.probeCounts.x * volume.probeCounts.y * volume.probeCounts.z;
    int probeIndex = int((gProbeBatchStart + launch.y
#if RASTER_PROBE_CAPTURE
        + gRasterOffset
#endif
    ) % uint(probeCount));
    if (rayIndex >= volume.probeNumRays || probeIndex >= probeCount) return;
    int3 probeCoords = DDGIGetProbeCoords(probeIndex, volume);
    probeIndex = DDGIGetScrollingProbeIndex(probeCoords, volume);

    float state = DDGILoadProbeState(probeIndex, gProbeData, volume);
    if (state == RTXGI_DDGI_PROBE_STATE_INACTIVE && rayIndex >= RTXGI_DDGI_NUM_FIXED_RAYS) return;

    float3 origin = DDGIGetProbeWorldPosition(probeCoords, volume, gProbeData);
    float3 direction = DDGIGetProbeRayDirection(rayIndex, volume);
    uint3 outputCoords = DDGIGetRayDataTexelCoords(rayIndex, probeIndex, volume);
    RayDesc ray;
    ray.Origin = origin;
    ray.Direction = direction;
    ray.TMin = 0.f;
    ray.TMax = volume.probeMaxRayDistance;
    ProbeRayPayload payload = {};
    payload.hitT = -1.f;
    // Back faces must be preserved for SDK relocation and classification.
#if RASTER_PROBE_CAPTURE
    uint face = cubeFace(direction);
    float2 uv = cubeUV(direction,face);
    uint2 pixel = min(uint2(saturate(uv)*gRasterSize),uint2(gRasterSize-1));
    uint4 packed = gRasterHits.Load(int4(pixel,launch.y*6+face,0));
#if HIT_INFO_USE_COMPRESSION
    HitInfo rasterHit = HitInfo(packed.xy);
#else
    HitInfo rasterHit = HitInfo(packed);
#endif
    if (rasterHit.isValid()) {
        VertexData v = gScene.getVertexData(rasterHit.getTriangleHit());
        payload.hit = rasterHit.data;
        payload.hitT = length(v.posW-origin);
        payload.backFace = dot(v.faceNormalW,normalize(v.posW-origin)) > 0.f;
        if (payload.hitT > volume.probeMaxRayDistance) payload.hitT = -1.f;
    }
#else
    TraceRay(gScene.rtAccel, RAY_FLAG_NONE, 0xff, 0, rayTypeCount, 0, ray, payload);
#endif

    if (payload.hitT < 0.f)
    {
        DDGIStoreProbeRayMiss(gRayData, outputCoords, volume, evaluateProbeMiss(direction));
        return;
    }
    if (payload.backFace != 0)
    {
        DDGIStoreProbeRayBackfaceHit(gRayData, outputCoords, volume, payload.hitT);
        return;
    }
    // Fixed directions exist for geometric tests, not the irradiance estimate.
    if ((volume.probeRelocationEnabled || volume.probeClassificationEnabled) && rayIndex < RTXGI_DDGI_NUM_FIXED_RAYS)
    {
        DDGIStoreProbeRayFrontfaceHit(gRayData, outputCoords, volume, payload.hitT);
        return;
    }

    ShadingData sd = loadTriangleSurface(HitInfo(payload.hit), direction);
    if (!validSurface(sd))
    {
        DDGIStoreProbeRayFrontfaceHit(gRayData, outputCoords, volume, float3(0.f), payload.hitT);
        return;
    }
    let material = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f));
    let properties = material.getProperties(sd);
    SampleGenerator sg = SampleGenerator(uint2(rayIndex, probeIndex), gFrameCount);
    float3 radiance = evaluateDirect(sd, material, true, sg);
    if (gHistoryValid)
    {
        float3 irradiance = queryIrradiance(sd.posW, sd.getOrientedFaceNormal(), direction, volume);
        // Match the SDK sample's feedback energy safeguard.
        float3 albedo = finiteRadiance(properties.diffuseReflectionAlbedo, 0u);
        radiance += min(albedo, float3(0.9f)) * irradiance / M_PI;
    }
    DDGIStoreProbeRayFrontfaceHit(gRayData, outputCoords, volume, finiteRadiance(radiance, 3u), payload.hitT);
}

#if FINAL_GATHER_SCREEN_CACHE
// Screen-space radiance cache: reproject a gather hit into the previous frame's
// gather samples. Valid only if the previous camera saw this same surface point
// from the same side; the stored color is that pixel's full outgoing radiance
// (direct + emission + gathered indirect), which is view-independent for Lambert.
bool screenCacheLookup(ShadingData sd, out float3 radiance)
{
    radiance = float3(0.f);
    if (!gScreenCacheValid) return false;
    float3 toCamera = gScreenCachePrevCamera - sd.posW;
    float cameraDistance = length(toCamera);
    if (!(cameraDistance > 0.f) || dot(sd.getOrientedFaceNormal(), toCamera) <= 0.f) return false;
    float4 clip = mul(gScreenCachePrevViewProj, float4(sd.posW, 1.f));
    if (!(clip.w > 0.f)) return false;
    float2 uv = clip.xy / clip.w * float2(0.5f, -0.5f) + 0.5f;
    if (any(uv < 0.f) || any(uv >= 1.f)) return false;
    uint width, height;
    gScreenCachePos.GetDimensions(width, height);
    float2 pixel = uv * float2(gFrameDim);
    // Nearest gather sample; half-resolution samples sit at 2q + offset.
    int2 texel = gHalfResolutionGather ? int2(floor((pixel - float2(gScreenCachePrevOffset) + 0.5f) * 0.5f)) : int2(pixel);
    texel = clamp(texel, int2(0), int2(width, height) - 1);
    float4 cachedPosition = gScreenCachePos[texel];
    // The visible surface must be this hit point, not an occluder or a neighbor.
    if (cachedPosition.w <= 0.f || length(cachedPosition.xyz - sd.posW) > gScreenCacheTolerance * cameraDistance) return false;
    radiance = gScreenCacheColor[texel].rgb;
    return all(isfinite(radiance));
}
#endif

#if SHARC_CACHE
#include "SharcTrace.slang"
#endif

// One camera-side reflection segment followed by DDGI termination.
// Reconstruct the material AFTER setting the lobe mask: StandardBSDF caches it.
// Each lobe is sampled independently, so sum the two estimates (do not average).
// With the idTech 8 caches enabled, a diffuse gather hit first reads the
// screen-space cache, then the world radiance cache, and only shades on a miss.
float3 gatherReflection(ShadingData primary, uint lobes, DDGIVolumeDescGPU volume, inout SampleGenerator sg, out float hitDistance)
{
    hitDistance = 0.f;
    primary.mtl.setActiveLobes(primary.mtl.getActiveLobes() & lobes);
    let source = gScene.materials.getMaterialInstance(primary, ExplicitLodTextureSampler(0.f), primaryMaterialHints());
    if ((source.getLobeTypes(primary) & lobes) == 0) return float3(0.f);
    BSDFSample sample = {};
    if (!source.sample(primary, sg, sample, true) || !any(sample.weight > 0.f)) return float3(0.f);
    if ((sample.lobeType & lobes) == 0) return float3(0.f);
    if (!all(isfinite(sample.wo)) || !all(isfinite(sample.weight)))
    {
        rejectNonFinite(0u);
        return float3(0.f);
    }
    if (dot(primary.getOrientedFaceNormal(), sample.wo) <= kMinCosTheta) return float3(0.f);
    RayDesc ray;
    ray.Origin = computeRayOrigin(primary.posW, dot(primary.faceN, sample.wo) >= 0.f ? primary.faceN : -primary.faceN);
    ray.Direction = sample.wo;
    ray.TMin = 0.f;
    ray.TMax = FLT_MAX;
    ProbeRayPayload payload = {};
    payload.hitT = -1.f;
    TraceRay(gScene.rtAccel, RAY_FLAG_NONE, 0xff, 0, rayTypeCount, 0, ray, payload);
    // Linear world-space distance for RELAX; finite FP16 maximum denotes a miss.
    hitDistance = payload.hitT < 0.f ? 65504.f : min(payload.hitT, 65504.f);
    float3 radiance = float3(0.f);
    if (payload.hitT < 0.f)
    {
        radiance = evaluateProbeMiss(sample.wo);
    }
    else
    {
        ShadingData sd = loadTriangleSurface(HitInfo(payload.hit), sample.wo);
        if (!validSurface(sd)) return float3(0.f);
#if SHARC_CACHE
        radiance = sharcQueryPath(sd, payload.hitT, sample.weight, sg);
#elif LUMEN_WORLD_CACHE
        if (!sd.frontFacing && !sd.mtl.isDoubleSided()) return float3(0.f);
        radiance = wcLookup(sd.posW, sd.getOrientedFaceNormal());
#else
        bool cached = false;
#if FG_USE_CACHES
        // Caches hold diffuse outgoing radiance; glossy lobes keep exact shading.
        uint cacheSource = 3u;
        if ((sample.lobeType & (uint)LobeType::DiffuseReflection) != 0 && (sd.frontFacing || sd.mtl.isDoubleSided()))
        {
#if FINAL_GATHER_SCREEN_CACHE
            if (screenCacheLookup(sd, radiance)) { cached = true; cacheSource = 1u; }
#endif
#if FG_USE_WRC
            if (!cached && wrcLookup(sd.posW, sd.getOrientedFaceNormal(), radiance))
            {
                cached = true;
                cacheSource = 2u;
                // WRC entries follow the DDGI probe estimator, which excludes the
                // hit's own emission. Add it here, as the shading fallback does.
                if (sd.mtl.isEmissive())
                {
                    let material = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f));
                    radiance += finiteRadiance(material.getProperties(sd).emission, 0u);
                }
            }
#endif
        }
        InterlockedAdd(gFgCacheCounters[0], 1u);
        InterlockedAdd(gFgCacheCounters[cacheSource], 1u);
#endif
        if (!cached)
        {
            let material = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f));
            let properties = material.getProperties(sd);
            radiance = finiteRadiance(properties.emission, 0u) + evaluateDirect(sd, material, false, sg);
            radiance += finiteRadiance(properties.diffuseReflectionAlbedo, 0u) *
                queryIrradiance(sd.posW, sd.getOrientedFaceNormal(), sample.wo, volume) / M_PI;
        }
#endif
    }
    return finiteRadiance(sample.weight * radiance, 3u);
}

// Two specialized entry points share the same estimator and random seeds.
void shadePixel(uint2 pixel, bool gatherOnly)
{
    if (any(pixel >= gFrameDim)) return;
    // One representative pixel per 2x2 block; reconstruction uses the same phase.
    bool gatherPixel = !gHalfResolutionGather || (all((pixel & 1u) == gGatherOffset) && all(pixel / 2u < max(gFrameDim / 2u, uint2(1))));
    uint2 gatherOutputPixel = gHalfResolutionGather ? pixel / 2u : pixel;
    DDGIVolumeDescGPU volume = (DDGIVolumeDescGPU)0;
#if !LUMEN_WORLD_CACHE && !SHARC_CACHE
    volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
#endif
    float3 direction = primaryRayDirection(pixel);
    float3 origin = gScene.camera.getPosition();
    HitInfo hit = HitInfo(gVBuffer[pixel]);
    float3 color = float3(0.f);
    float3 indirect = float3(0.f);
    float3 gatheredDiffuse = float3(0.f), gatheredSpecular = float3(0.f);
    float diffuseHitDistance = 0.f, specularHitDistance = 0.f;
    float3 diffuseReflectance = float3(0.f), specularReflectance = float3(0.f);
    bool useExternalDirect = false;
#if HAS_DIRECT_LIGHTING
    useExternalDirect = gUseRTXDI && !gFinalGather;
    // RTXDIPass.color already includes surface emission and environment background.
    // Only the camera lighting changes; probe rays keep their own direct-light estimator.
    if (useExternalDirect && !gIndirectOnly) color = finiteRadiance(gDirectLighting[pixel].rgb, 1u);
#endif
    float surfaceDistance = FLT_MAX;
    float3 surfacePosition = float3(0.f);
    if (hit.isValid())
    {
        ShadingData sd = loadTriangleSurface(hit, direction);
        surfaceDistance = length(sd.posW - origin);
        surfacePosition = sd.posW;
        let material = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f), primaryMaterialHints());
        let properties = material.getProperties(sd);
        // A positive floor prevents unstable demodulation of supported lobes;
        // absent lobes stay zero so spatial filtering cannot invent a response.
        uint materialLobes = material.getLobeTypes(sd);
        if ((materialLobes & (uint)LobeType::DiffuseReflection) != 0)
            diffuseReflectance = max(finiteRadiance(properties.diffuseReflectionAlbedo, 0u), float3(1e-4f));
        if ((materialLobes & ((uint)LobeType::SpecularReflection | (uint)LobeType::DeltaReflection)) != 0)
            specularReflectance = max(approxSpecularIntegralGGX(properties.specularReflectance,
                properties.roughness * properties.roughness, saturate(dot(properties.guideNormal, sd.V))), float3(1e-4f));
        if (!gatherOnly && !gIndirectOnly && !useExternalDirect && validSurface(sd))
        {
            SampleGenerator sg = SampleGenerator(pixel, gFrameCount);
            // Gather rays sample emissive geometry and the environment themselves.
            // Only analytic lights use primary NEE in this reference estimator;
            // adding emissive/environment NEE here without MIS would double count.
            color = finiteRadiance(properties.emission, 0u) + (gFinalGather ?
                evaluateAnalyticDirect(sd, material, false, sg) : evaluateDirect(sd, material, false, sg, primaryMaterialHints()));
        }
        if (!RESTIR_GATHER && gEnableGI && validSurface(sd) && (gatherOnly || !SPLIT_HALF_GATHER))
        {
            if (gFinalGather)
            {
                SampleGenerator sg = SampleGenerator(pixel, gFrameCount);
                // Decorrelate gather from the primary direct-light estimator.
                sampleNext2D(sg);
                if (gGatherDiffuse && gatherPixel)
                {
                    gatheredDiffuse = gatherReflection(sd, (uint)LobeType::DiffuseReflection, volume, sg, diffuseHitDistance);
                    gatheredDiffuse *= gIntensity;
                }
                if (gGatherSpecular && gatherPixel)
                    gatheredSpecular = gatherReflection(sd, (uint)LobeType::SpecularReflection | (uint)LobeType::DeltaReflection, volume, sg, specularHitDistance) * gIntensity;
                indirect = gatheredDiffuse + gatheredSpecular;
            }
            else
                indirect = finiteRadiance(properties.diffuseReflectionAlbedo, 0u) *
                    queryIrradiance(sd.posW, sd.getOrientedFaceNormal(), direction, volume) * (gIntensity / M_PI);
            indirect = finiteRadiance(indirect, 3u);
            color += indirect;
        }
    }
#if USE_ENV_BACKGROUND
    else if (!gatherOnly && !gIndirectOnly && !useExternalDirect)
    {
        color = evaluateSafeEnvironment(direction);
    }
#endif
#if OUTPUT_GATHER_DIFFUSE
    gOutputGatherDiffuse[pixel] = float4(gatheredDiffuse, 1.f);
#endif
#if OUTPUT_GATHER_SPECULAR
    gOutputGatherSpecular[pixel] = float4(gatheredSpecular, 1.f);
#endif
    if (gShowWrcCells && !gatherOnly) gWrcDebugDepth[pixel] = surfaceDistance;
#if OUTPUT_DIFFUSERADIANCEHITDIST
    if (gatherPixel && (gatherOnly || !SPLIT_HALF_GATHER)) gDiffuseRadianceHitDist[gatherOutputPixel] = float4(gatheredDiffuse / max(diffuseReflectance, float3(1e-4f)), diffuseHitDistance);
#endif
#if OUTPUT_SPECULARRADIANCEHITDIST
    if (gatherPixel && (gatherOnly || !SPLIT_HALF_GATHER)) gSpecularRadianceHitDist[gatherOutputPixel] = float4(gatheredSpecular / max(specularReflectance, float3(1e-4f)), specularHitDistance);
#endif
#if OUTPUT_DIFFUSEREFLECTANCE
    if (!gatherOnly) gDiffuseReflectance[pixel] = float4(diffuseReflectance, 1.f);
#endif
#if OUTPUT_SPECULARREFLECTANCE
    if (!gatherOnly) gSpecularReflectance[pixel] = float4(specularReflectance, 1.f);
#endif
#if OUTPUT_UNFILTEREDCOLOR
    // Direct/emission/background and legacy probe mode bypass NRD.
    if (!gatherOnly) gUnfilteredColor[pixel] = float4(finiteRadiance(color - gatheredDiffuse - gatheredSpecular, 3u), 1.f);
#endif
    if (gatherOnly) color += gOutputColor[pixel].rgb;
    gOutputColor[pixel] = float4(finiteRadiance(color, 3u), 1.f);
#if FINAL_GATHER_SCREEN_CACHE
    // Store this gather pixel's outgoing radiance for next frame's gather rays.
    // With split half-resolution gather, only the second pass has the full sum.
    if (gatherPixel && (gatherOnly || !SPLIT_HALF_GATHER))
    {
        bool valid = hit.isValid() && !gIndirectOnly && surfaceDistance < FLT_MAX;
        gScreenCacheColorOut[gatherOutputPixel] = float4(valid ? finiteRadiance(color, 3u) : float3(0.f), 1.f);
        gScreenCachePosOut[gatherOutputPixel] = float4(surfacePosition, valid ? 1.f : 0.f);
    }
#endif
#if OUTPUT_INDIRECT
    gOutputIndirect[pixel] = float4(indirect, 1.f);
#endif
}

[shader("raygeneration")]
void render()
{
    shadePixel(DispatchRaysIndex().xy, false);
}

[shader("raygeneration")]
void gatherHalf()
{
    shadePixel(DispatchRaysIndex().xy * 2u + gGatherOffset, true);
}

[shader("miss")]
void probeMiss(inout ProbeRayPayload payload)
{
    payload.hitT = -1.f;
}

[shader("miss")]
void shadowMiss(inout ShadowRayPayload payload)
{
    payload.visible = true;
}

[shader("closesthit")]
void probeTriangleClosestHit(inout ProbeRayPayload payload, BuiltInTriangleIntersectionAttributes attributes)
{
    TriangleHit hit;
    hit.instanceID = getGeometryInstanceID();
    hit.primitiveIndex = PrimitiveIndex();
    hit.barycentrics = attributes.barycentrics;
    payload.hit = HitInfo(hit).pack();
    payload.hitT = RayTCurrent();
    payload.backFace = HitKind() == HIT_KIND_TRIANGLE_BACK_FACE ? 1u : 0u;
}

bool rejectedByAlphaTest(BuiltInTriangleIntersectionAttributes attributes)
{
    GeometryInstanceID instanceID = getGeometryInstanceID();
    VertexData vertex = getVertexData(instanceID, PrimitiveIndex(), attributes);
    return gScene.materials.alphaTest(vertex, gScene.getMaterialID(instanceID), 0.f);
}

[shader("anyhit")]
void probeTriangleAnyHit(inout ProbeRayPayload payload, BuiltInTriangleIntersectionAttributes attributes)
{
    if (rejectedByAlphaTest(attributes)) IgnoreHit();
}

[shader("anyhit")]
void shadowTriangleAnyHit(inout ShadowRayPayload payload, BuiltInTriangleIntersectionAttributes attributes)
{
    if (rejectedByAlphaTest(attributes)) IgnoreHit();
}

#include "ReSTIRGather.slang"

#if LUMEN_WORLD_CACHE
#include "LumenWorldCacheTrace.slang"
#endif
