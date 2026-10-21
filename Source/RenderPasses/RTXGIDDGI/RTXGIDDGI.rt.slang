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

// Falcor scene/material bridge for the unmodified NVIDIA RTXGI-DDGI SDK.
// Intersection, alpha testing and analytic-light sampling follow MinimalPathTracer.
// Only triangle meshes are supported by this first integration. Glass is treated
// as a geometric boundary; there is no specular-indirect or transmission path.
// The SDK owns ray directions, encoding, relocation/classification, and querying.

#include "Scene/SceneDefines.slangh"
#include "Utils/Math/MathConstants.slangh"
#include "RTXGIConfig.slang"
#include "RTXGI/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl"

import Scene.Raytracing;
import Scene.Intersection;
import Utils.Math.MathHelpers;
import Utils.Geometry.GeometryHelpers;
import Utils.Sampling.SampleGenerator;
import Rendering.Lights.LightHelpers;
import Rendering.Lights.EmissiveUniformSampler;
import Rendering.Lights.EmissiveLightSamplerInterface;
import Rendering.Lights.EnvMapSampler;

cbuffer PerFrameCB
{
    uint gFrameCount;
    uint2 gFrameDim;
    bool gEnableGI;
    bool gIndirectOnly;
    bool gShowProbes;
    bool gHistoryValid;
    float gIntensity; // Display scaling only; recursive transport stays physical.
    float gProbeRadius; // World-space radius of the optional diagnostic spheres.
}

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
RWTexture2D<float4> gOutputColor;
#if OUTPUT_INDIRECT
RWTexture2D<float4> gOutputIndirect;
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
}

float3 evaluateBRDFCosine(ShadingData sd, IMaterialInstance material, float3 direction, bool diffuseOnly, inout SampleGenerator sg)
{
    if (dot(sd.getOrientedFaceNormal(), direction) <= kMinCosTheta) return float3(0.f);
    if (diffuseOnly)
    {
        float3 albedo = finiteRadiance(material.getProperties(sd).diffuseReflectionAlbedo, 0u);
        return albedo * (max(0.f, dot(sd.frame.N, direction)) / M_PI);
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

float3 evaluateEnvironmentDirect(ShadingData sd, IMaterialInstance material, bool diffuseOnly, inout SampleGenerator sg)
{
#if USE_ENV_LIGHT
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
    float3 brdfCosine = evaluateBRDFCosine(sd, material, light.dir, diffuseOnly, sg);
    return finiteRadiance(brdfCosine * (light.Le / light.pdf), 1u);
#else
    return float3(0.f);
#endif
}

float3 evaluateDirect(ShadingData sd, IMaterialInstance material, bool diffuseOnly, inout SampleGenerator sg)
{
    // One sample from EACH enabled light category, so there is no category PDF.
    float3 radiance = evaluateAnalyticDirect(sd, material, diffuseOnly, sg);
    radiance += evaluateEmissiveDirect(sd, material, diffuseOnly, sg);
    radiance += evaluateEnvironmentDirect(sd, material, diffuseOnly, sg);
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
    int probeIndex = int(launch.z) * DDGIGetProbesPerPlane(volume.probeCounts) + int(launch.y);
    int probeCount = volume.probeCounts.x * volume.probeCounts.y * volume.probeCounts.z;
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
    TraceRay(gScene.rtAccel, RAY_FLAG_NONE, 0xff, 0, rayTypeCount, 0, ray, payload);

    if (payload.hitT < 0.f)
    {
        // Direct environment and emissive illumination are sampled explicitly
        // at surfaces. The DDGI field stores only light scattered by geometry.
        DDGIStoreProbeRayMiss(gRayData, outputCoords, volume, float3(0.f));
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

// Diagnostic sphere overlay: active probes are green, inactive probes red.
// Uses the SDK-relocated positions, and normal scene depth occludes the spheres.
// Intentionally optional: this O(probeCount) debug path is not a GI benchmark.
float3 overlayProbes(float3 color, float3 origin, float3 direction, float sceneDistance, DDGIVolumeDescGPU volume)
{
    int count = volume.probeCounts.x * volume.probeCounts.y * volume.probeCounts.z;
    float radius = gProbeRadius;
    float nearest = sceneDistance;
    int selected = -1;
    float3 selectedNormal = float3(0.f);
    for (int index = 0; index < count; ++index)
    {
        int3 coords = DDGIGetProbeCoords(index, volume);
        float3 center = DDGIGetProbeWorldPosition(coords, volume, gProbeData);
        float3 offset = origin - center;
        float b = dot(offset, direction);
        float discriminant = b * b - dot(offset, offset) + radius * radius;
        if (discriminant < 0.f) continue;
        float distance = -b - sqrt(discriminant);
        if (distance <= 0.f || distance >= nearest) continue;
        nearest = distance;
        selected = DDGIGetScrollingProbeIndex(coords, volume);
        selectedNormal = normalize(origin + direction * distance - center);
    }
    if (selected >= 0)
    {
        float state = DDGILoadProbeState(selected, gProbeData, volume);
        float3 tint = state == RTXGI_DDGI_PROBE_STATE_INACTIVE ? float3(0.9f, 0.06f, 0.02f) : float3(0.05f, 0.8f, 0.15f);
        color = tint * (0.25f + 0.75f * max(0.f, dot(selectedNormal, -direction)));
    }
    return color;
}

[shader("raygeneration")]
void render()
{
    uint2 pixel = DispatchRaysIndex().xy;
    if (any(pixel >= gFrameDim)) return;
    DDGIVolumeDescGPU volume = UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
    float3 direction = primaryRayDirection(pixel);
    float3 origin = gScene.camera.getPosition();
    HitInfo hit = HitInfo(gVBuffer[pixel]);
    float3 color = float3(0.f);
    float3 indirect = float3(0.f);
    float surfaceDistance = FLT_MAX;
    if (hit.isValid())
    {
        ShadingData sd = loadTriangleSurface(hit, direction);
        surfaceDistance = length(sd.posW - origin);
        let material = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f));
        let properties = material.getProperties(sd);
        if (!gIndirectOnly && validSurface(sd))
        {
            SampleGenerator sg = SampleGenerator(pixel, gFrameCount);
            color = finiteRadiance(properties.emission, 0u) + evaluateDirect(sd, material, false, sg);
        }
        if (gEnableGI && validSurface(sd))
        {
            indirect = finiteRadiance(properties.diffuseReflectionAlbedo, 0u) *
                queryIrradiance(sd.posW, sd.getOrientedFaceNormal(), direction, volume) * (gIntensity / M_PI);
            indirect = finiteRadiance(indirect, 3u);
            color += indirect;
        }
    }
#if USE_ENV_BACKGROUND
    else if (!gIndirectOnly)
    {
        color = evaluateSafeEnvironment(direction);
    }
#endif
    if (gShowProbes) color = overlayProbes(color, origin, direction, surfaceDistance, volume);
    gOutputColor[pixel] = float4(finiteRadiance(color, 3u), 1.f);
#if OUTPUT_INDIRECT
    gOutputIndirect[pixel] = float4(indirect, 1.f);
#endif
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
