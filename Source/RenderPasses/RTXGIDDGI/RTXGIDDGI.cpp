#include "RTXGIDDGI.h"
#include "DDGIReconstruct.h"
#include "RenderGraph/RenderPassHelpers.h"
#include "RenderGraph/RenderPassStandardFlags.h"
#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable : 4515) // SDK headers intentionally include shared types inside namespace rtxgi.
#endif
#include <rtxgi/ddgi/DDGIVolume.h>
#ifdef _MSC_VER
#pragma warning(pop)
#endif
#include <cmath>
#include <cstring>
#include <limits>

namespace
{
const char kRayShader[] = "RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang";
const char kWrcShader[] = "RenderPasses/RTXGIDDGI/WorldRadianceCache.rt.slang";
const char kWrcComputeShader[] = "RenderPasses/RTXGIDDGI/WorldRadianceCache.cs.slang";
const char kWrcDebugShader[] = "RenderPasses/RTXGIDDGI/WorldRadianceCacheDebug.slang";
const ChannelList kInputs = {
    {"vbuffer", "gVBuffer", "Camera surface visibility"},
    {"viewW", "gViewW", "Camera view direction", true},
    {"mvec", "gMotionVectors", "Screen-space motion vectors (optional)", true},
    {"directLighting", "gDirectLighting", "External direct lighting including emission and background (RTXDI)", true},
};
const ChannelList kOutputs = {
    {"restirDebug", "gRestirDebug", "Temporal M, spatial M, integration sample count", true, ResourceFormat::RGBA32Float},
    {"color", "gOutputColor", "Direct light, emission, and dynamic DDGI", false, ResourceFormat::RGBA32Float},
    {"indirect", "gOutputIndirect", "Probe diffuse or total final-gather contribution", true, ResourceFormat::RGBA32Float},
    {"gatherDiffuse", "gOutputGatherDiffuse", "Final-gather diffuse reflection", true, ResourceFormat::RGBA32Float},
    {"gatherSpecular", "gOutputGatherSpecular", "Final-gather specular reflection", true, ResourceFormat::RGBA32Float},
    {"diffuseRadianceHitDist", "gDiffuseRadianceHitDist", "Final gather NRD diffuseRadianceHitDist", true, ResourceFormat::RGBA32Float},
    {"specularRadianceHitDist", "gSpecularRadianceHitDist", "Final gather NRD specularRadianceHitDist", true, ResourceFormat::RGBA32Float},
    {"diffuseReflectance", "gDiffuseReflectance", "Final gather NRD diffuseReflectance", true, ResourceFormat::RGBA32Float},
    {"specularReflectance", "gSpecularReflectance", "Final gather NRD specularReflectance", true, ResourceFormat::RGBA32Float},
    {"unfilteredColor", "gUnfilteredColor", "Final gather NRD unfilteredColor", true, ResourceFormat::RGBA32Float},
};
const ResourceBindFlags kTextureFlags = ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess;

void registerBindings(pybind11::module& module)
{
    pybind11::class_<RTXGIDDGI, RenderPass, ref<RTXGIDDGI>> pass(module, "RTXGIDDGI");
    pass.def("reset", &RTXGIDDGI::reset);
    pass.def_property_readonly("updatedFrames", &RTXGIDDGI::getUpdatedFrames);
    pass.def_property_readonly("status", &RTXGIDDGI::getStatus);
    pass.def_property_readonly("stats", [](const RTXGIDDGI& self) { return self.getStats().toPython(); });
}
}

extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry)
{
    registry.registerClass<RenderPass, RTXGIDDGI>();
    registry.registerClass<RenderPass, DDGIReconstruct>();
    ScriptBindings::registerBinding(registerBindings);
}

RTXGIDDGI::RTXGIDDGI(ref<Device> device, const Properties& properties) : RenderPass(device)
{
    mpDevice->requireD3D12();
    setProperties(properties);
    mpSampleGenerator = SampleGenerator::create(mpDevice, SAMPLE_GENERATOR_UNIFORM);
    Sampler::Desc sampler;
    sampler.setFilterMode(TextureFilteringMode::Linear, TextureFilteringMode::Linear, TextureFilteringMode::Point);
    sampler.setAddressingMode(TextureAddressingMode::Clamp, TextureAddressingMode::Clamp, TextureAddressingMode::Clamp);
    mpSampler = mpDevice->createSampler(sampler);
}

Properties RTXGIDDGI::getProperties() const
{
    Properties p;
    p["worldCache"] = mOptions.worldCache;
    p["worldCacheDownsample"] = mOptions.worldCacheDownsample;
    p["worldCacheBounces"] = mOptions.worldCacheBounces;
    p["worldCacheHistory"] = mOptions.worldCacheHistory;
    p["worldCacheDensity"] = mOptions.worldCacheDensity;
    p["worldCacheMaxIntensity"] = mOptions.worldCacheMaxIntensity;
    p["gridCounts"] = mOptions.counts;
    p["raysPerProbe"] = mOptions.rays;
    p["hysteresis"] = mOptions.hysteresis;
    p["normalBias"] = mOptions.normalBias;
    p["viewBias"] = mOptions.viewBias;
    p["minFrontfaceDistance"] = mOptions.minFrontfaceDistance;
    p["intensity"] = mOptions.intensity;
    p["gridMin"] = mOptions.gridMin;
    p["gridMax"] = mOptions.gridMax;
    p["autoBounds"] = mOptions.autoBounds;
    p["enableRelocation"] = mOptions.relocation;
    p["enableClassification"] = mOptions.classification;
    p["updateEnabled"] = mOptions.update;
    p["finalGather"] = mOptions.finalGather;
    p["halfResolutionGather"] = mOptions.halfResolutionGather;
    p["jitterHalfGather"] = mOptions.jitterHalfGather;
    p["restirTemporal"] = mOptions.restirTemporal;
    p["restirSpatial"] = mOptions.restirSpatial;
    p["restirSpatialFeedback"] = mOptions.restirSpatialFeedback;
    p["restirTemporalCellMapping"] = mOptions.restirTemporalCellMapping;
    p["restirBiasCorrection"] = mOptions.restirBiasCorrection;
    p["restirSpatialSamples"] = mOptions.restirSpatialSamples;
    p["restirIntegrateSamples"] = mOptions.restirIntegrateSamples;
    p["restirSpatialRadius"] = mOptions.restirSpatialRadius;
    p["restirSpatialPasses"] = mOptions.restirSpatialPasses;
    p["restirIntegrateRadius"] = mOptions.restirIntegrateRadius;
    p["restirFullResolution"] = mOptions.restirFullResolution;
    p["restirGather"] = mOptions.restirGather;
    p["restirHistoryLength"] = mOptions.restirHistoryLength;
    p["restirMaxAge"] = mOptions.restirMaxAge;
    p["gatherDiffuse"] = mOptions.gatherDiffuse;
    p["gatherSpecular"] = mOptions.gatherSpecular;
    p["enableGI"] = mOptions.enableGI;
    p["showProbes"] = mOptions.showProbes;
    p["indirectOnly"] = mOptions.indirectOnly;
    p["useRTXDI"] = mOptions.useRTXDI;
    p["useWRC"] = mOptions.useWRC;
    p["wrcGroupByMaterial"] = mOptions.wrcGroupByMaterial;
    p["wrcStressMode"] = mOptions.wrcStressMode;
    p["wrcStressIterations"] = mOptions.wrcStressIterations;
    p["wrcStressStats"] = mOptions.wrcStressStats;
    p["wrcCellScale"] = mOptions.wrcCellScale;
    p["wrcLodDistance"] = mOptions.wrcLodDistance;
    p["wrcMaxLod"] = mOptions.wrcMaxLod;
    p["wrcProbeLimit"] = mOptions.wrcProbeLimit;
    p["wrcTableSize"] = mOptions.wrcTableSize;
    p["wrcMaxAge"] = mOptions.wrcMaxAge;
    p["wrcShadeSamples"] = mOptions.wrcShadeSamples;
    p["wrcBypassSharing"] = mOptions.wrcBypassSharing;
    p["showWrcCells"] = mOptions.showWrcCells;
    p["wrcCellsXRay"] = mOptions.wrcCellsXRay;
    p["wrcCellsLod"] = mOptions.wrcCellsLod;
    p["wrcCellsOpacity"] = mOptions.wrcCellsOpacity;
    return p;
}

void RTXGIDDGI::setProperties(const Properties& properties)
{
    Options next = mOptions;
    bool refreshLighting = false;
    for (const auto& [name, value] : properties)
    {
        refreshLighting |= name != "showWrcCells" && name != "wrcCellsXRay" &&
                           name != "wrcCellsLod" && name != "wrcCellsOpacity";
        if (name == "worldCache") next.worldCache = value;
        else if (name == "worldCacheDownsample") next.worldCacheDownsample = value;
        else if (name == "worldCacheBounces") next.worldCacheBounces = value;
        else if (name == "worldCacheHistory") next.worldCacheHistory = value;
        else if (name == "worldCacheMaxIntensity") next.worldCacheMaxIntensity = value;
        else if (name == "worldCacheDensity") next.worldCacheDensity = value;
        else if (name == "gridCounts") next.counts = value;
        else if (name == "raysPerProbe") next.rays = value;
        else if (name == "hysteresis") next.hysteresis = value;
        else if (name == "normalBias") next.normalBias = value;
        else if (name == "viewBias") next.viewBias = value;
        else if (name == "minFrontfaceDistance") next.minFrontfaceDistance = value;
        else if (name == "intensity") next.intensity = value;
        else if (name == "gridMin") next.gridMin = value;
        else if (name == "gridMax") next.gridMax = value;
        else if (name == "autoBounds") next.autoBounds = value;
        else if (name == "enableRelocation") next.relocation = value;
        else if (name == "enableClassification") next.classification = value;
        else if (name == "updateEnabled") next.update = value;
        else if (name == "finalGather") next.finalGather = value;
        else if (name == "halfResolutionGather") next.halfResolutionGather = value;
        else if (name == "jitterHalfGather") next.jitterHalfGather = value;
        else if (name == "restirTemporal") next.restirTemporal = value;
        else if (name == "restirSpatial") next.restirSpatial = value;
        else if (name == "restirSpatialFeedback") next.restirSpatialFeedback = value;
        else if (name == "restirTemporalCellMapping") next.restirTemporalCellMapping = value;
        else if (name == "restirBiasCorrection") next.restirBiasCorrection = value;
        else if (name == "restirSpatialSamples") next.restirSpatialSamples = value;
        else if (name == "restirIntegrateSamples") next.restirIntegrateSamples = value;
        else if (name == "restirSpatialRadius") next.restirSpatialRadius = value;
        else if (name == "restirSpatialPasses") next.restirSpatialPasses = value;
        else if (name == "restirIntegrateRadius") next.restirIntegrateRadius = value;
        else if (name == "restirFullResolution") next.restirFullResolution = value;
        else if (name == "restirGather") next.restirGather = value;
        else if (name == "restirHistoryLength") next.restirHistoryLength = value;
        else if (name == "restirMaxAge") next.restirMaxAge = value;
        else if (name == "gatherDiffuse") next.gatherDiffuse = value;
        else if (name == "gatherSpecular") next.gatherSpecular = value;
        else if (name == "enableGI") next.enableGI = value;
        else if (name == "showProbes") next.showProbes = value;
        else if (name == "indirectOnly") next.indirectOnly = value;
        else if (name == "useRTXDI") next.useRTXDI = value;
        else if (name == "useWRC") next.useWRC = value;
        else if (name == "wrcGroupByMaterial") next.wrcGroupByMaterial = value;
        else if (name == "wrcStressMode") next.wrcStressMode = value;
        else if (name == "wrcStressIterations") next.wrcStressIterations = value;
        else if (name == "wrcStressStats") next.wrcStressStats = value;
        else if (name == "wrcCellScale") next.wrcCellScale = value;
        else if (name == "wrcLodDistance") next.wrcLodDistance = value;
        else if (name == "wrcMaxLod") next.wrcMaxLod = value;
        else if (name == "wrcProbeLimit") next.wrcProbeLimit = value;
        else if (name == "wrcTableSize") next.wrcTableSize = value;
        else if (name == "wrcMaxAge") next.wrcMaxAge = value;
        else if (name == "wrcShadeSamples") next.wrcShadeSamples = value;
        else if (name == "wrcBypassSharing") next.wrcBypassSharing = value;
        else if (name == "showWrcCells") next.showWrcCells = value;
        else if (name == "wrcCellsXRay") next.wrcCellsXRay = value;
        else if (name == "wrcCellsLod") next.wrcCellsLod = value;
        else if (name == "wrcCellsOpacity") next.wrcCellsOpacity = value;
        else FALCOR_THROW("Unknown RTXGIDDGI property '{}'.", name);
    }
    FALCOR_CHECK(all(next.counts >= uint3(2)) && all(next.counts <= uint3(32)), "DDGI gridCounts must be 2..32 per axis.");
    FALCOR_CHECK(next.rays >= 64 && next.rays <= 512, "DDGI raysPerProbe must be 64..512 (32 rays are reserved for probe placement).");
    FALCOR_CHECK(std::isfinite(next.hysteresis) && next.hysteresis >= 0.f && next.hysteresis < 1.f, "DDGI hysteresis must be in [0,1).");
    FALCOR_CHECK(std::isfinite(next.normalBias) && next.normalBias >= 0.f && next.normalBias <= 1.f, "DDGI normalBias must be in [0,1].");
    FALCOR_CHECK(std::isfinite(next.viewBias) && next.viewBias >= 0.f && next.viewBias <= 1.f, "DDGI viewBias must be in [0,1].");
    FALCOR_CHECK(std::isfinite(next.minFrontfaceDistance) && next.minFrontfaceDistance >= 0.f && next.minFrontfaceDistance <= 1.f,
        "DDGI minFrontfaceDistance must be in [0,1] times the minimum probe spacing.");
    FALCOR_CHECK(std::isfinite(next.intensity) && next.intensity >= 0.f, "DDGI intensity must be finite and nonnegative.");
    FALCOR_CHECK(all(isfinite(next.gridMin)) && all(isfinite(next.gridMax)) && all(next.gridMax > next.gridMin), "DDGI gridMax must exceed gridMin.");
    FALCOR_CHECK(std::isfinite(next.wrcCellScale) && next.wrcCellScale >= 0.01f && next.wrcCellScale <= 2.f,
        "WRC cell scale must be 0.01..2 times the smallest probe spacing.");
    FALCOR_CHECK(std::isfinite(next.wrcLodDistance) && next.wrcLodDistance >= 0.1f && next.wrcLodDistance <= 128.f,
        "WRC LOD distance must be 0.1..128 times the smallest probe spacing.");
    FALCOR_CHECK(next.wrcMaxLod >= 1 && next.wrcMaxLod <= 64 && (next.wrcMaxLod & (next.wrcMaxLod - 1)) == 0,
        "WRC maximum LOD scale must be a power of two between 1 and 64.");
    FALCOR_CHECK(next.wrcProbeLimit >= 1 && next.wrcProbeLimit <= 64, "WRC linear probe limit must be 1..64.");
    FALCOR_CHECK(next.wrcTableSize >= 64 && next.wrcTableSize <= 1048576 && (next.wrcTableSize & (next.wrcTableSize - 1)) == 0,
        "WRC table size must be a power of two between 64 and 1048576.");
    FALCOR_CHECK(next.wrcMaxAge <= 8, "WRC max age must be 0..8 probe updates.");
    FALCOR_CHECK(next.wrcStressMode <= 2, "WRC stress mode must be 0 (off), 1 (common), or 2 (per type).");
    FALCOR_CHECK(next.wrcStressIterations <= 10000, "WRC stress iterations must be 0..10000.");
    FALCOR_CHECK(next.wrcShadeSamples >= 1 && next.wrcShadeSamples <= 8, "WRC shading samples must be 1..8.");
    FALCOR_CHECK(next.wrcCellsLod <= 64 && (next.wrcCellsLod == 0 || (next.wrcCellsLod & (next.wrcCellsLod - 1)) == 0),
        "WRC cell overlay LOD must be 0 or a power of two through 64.");
    FALCOR_CHECK(std::isfinite(next.wrcCellsOpacity) && next.wrcCellsOpacity >= 0.f && next.wrcCellsOpacity <= 1.f,
        "WRC cell overlay opacity must be in [0,1].");
    if (any(next.counts != mOptions.counts) || next.rays != mOptions.rays || next.autoBounds != mOptions.autoBounds ||
        any(next.gridMin != mOptions.gridMin) || any(next.gridMax != mOptions.gridMax)) mReallocate = true;
    if (next.relocation != mOptions.relocation || next.classification != mOptions.classification) mResetPending = true;
    if (next.minFrontfaceDistance != mOptions.minFrontfaceDistance) mResetPending = true;
    if (next.normalBias != mOptions.normalBias || next.viewBias != mOptions.viewBias) mWrcResetPending = true;
    // Invalidate the old active-list layout, including when probe updates are frozen.
    // Scheduling changes preserve the accumulated DDGI field.
    if (next.wrcGroupByMaterial != mOptions.wrcGroupByMaterial) mWrcResetPending = true;
    if (next.wrcStressMode != mOptions.wrcStressMode || next.wrcStressIterations != mOptions.wrcStressIterations)
        mWrcResetPending = true;
    if (next.wrcTableSize != mOptions.wrcTableSize) mWrcReallocate = true;
    if (next.useWRC != mOptions.useWRC || next.wrcCellScale != mOptions.wrcCellScale ||
        next.wrcLodDistance != mOptions.wrcLodDistance || next.wrcMaxLod != mOptions.wrcMaxLod ||
        next.wrcProbeLimit != mOptions.wrcProbeLimit ||
        next.wrcTableSize != mOptions.wrcTableSize || next.wrcMaxAge != mOptions.wrcMaxAge ||
        next.wrcShadeSamples != mOptions.wrcShadeSamples || next.wrcBypassSharing != mOptions.wrcBypassSharing)
        mResetPending = mWrcResetPending = true;
    if (next.halfResolutionGather != mOptions.halfResolutionGather || next.restirGather != mOptions.restirGather ||
        next.finalGather != mOptions.finalGather || next.enableGI != mOptions.enableGI || next.restirFullResolution != mOptions.restirFullResolution) requestRecompile();
    FALCOR_CHECK(next.restirSpatialSamples <= 16 && next.restirIntegrateSamples >= 1 && next.restirIntegrateSamples <= 16, "ReSTIR sample counts must be within 0..16 (integration >=1).");
    FALCOR_CHECK(std::isfinite(next.restirSpatialRadius) && next.restirSpatialRadius >= 1.f && next.restirSpatialRadius <= 64.f, "ReSTIR spatial radius must be 1..64.");
    FALCOR_CHECK(next.restirHistoryLength >= 1 && next.restirHistoryLength <= 32, "ReSTIR history length must be 1..32 candidates.");
    FALCOR_CHECK(next.restirSpatialPasses >= 1 && next.restirSpatialPasses <= 4, "ReSTIR spatial passes must be 1..4.");
    FALCOR_CHECK(std::isfinite(next.restirIntegrateRadius) && next.restirIntegrateRadius >= 0.f && next.restirIntegrateRadius <= 8.f, "ReSTIR integration radius must be 0..8.");
    FALCOR_CHECK(next.worldCacheDownsample >= 1 && next.worldCacheDownsample <= 32 &&
        next.worldCacheBounces >= 1 && next.worldCacheBounces <= 8 &&
        next.worldCacheHistory >= 1 && next.worldCacheHistory <= 255 &&
        std::isfinite(next.worldCacheMaxIntensity) && next.worldCacheMaxIntensity >= 0.f &&
        std::isfinite(next.worldCacheDensity) && next.worldCacheDensity >= 1.f && next.worldCacheDensity <= 63.f,
        "Invalid WorldCache settings.");
    if (next.worldCache) { next.finalGather = true; next.restirGather = false; next.showProbes = false; next.useWRC = false; next.showWrcCells = false; }
    if (next.worldCache != mOptions.worldCache)
    {
        mReallocate = mResetPending = mRebuildPrograms = true;
        requestRecompile();
    }
    if (next.worldCacheMaxIntensity != mOptions.worldCacheMaxIntensity || next.worldCacheDensity != mOptions.worldCacheDensity || next.worldCacheBounces != mOptions.worldCacheBounces)
        mWorldCacheReset = true;
    mRestirResetPending |= refreshLighting;
    mOptions = next;
    mOptionsChanged |= refreshLighting;
}

RenderPassReflection RTXGIDDGI::reflect(const CompileData& data)
{
    RenderPassReflection reflection;
    addRenderPassInputs(reflection, kInputs);
    addRenderPassOutputs(reflection, kOutputs);
    if (mOptions.halfResolutionGather && !(restirActive() && mOptions.restirFullResolution))
    {
        const uint2 size = restirActive() ? (data.defaultTexDims + uint2(1)) / uint2(2) : max(data.defaultTexDims / uint2(2), uint2(1));
        for (const char* name : {"diffuseRadianceHitDist", "specularRadianceHitDist"})
            reflection.getField(name)->texture2D(size.x, size.y);
    }
    reflection.getField("color")->bindFlags(kTextureFlags | ResourceBindFlags::RenderTarget);
    return reflection;
}

void RTXGIDDGI::setScene(RenderContext* context, const ref<Scene>& scene)
{
    mpScene = scene;
    mWorldCacheReset = true;
    mpRestirInitial = mpRestirTemporal = mpRestirSpatial = mpRestirHistory = nullptr;
    mRestirHistoryValid = false;
    mRestirResetPending = true;
    mTrace = {};
    mRender = {};
    mHalfGather = {};
    mWrcTrace = {};
    mpWrcBuild = mpWrcPrepare = mpWrcShade = mpWrcGather = nullptr;
    mWrcReallocate = mWrcResetPending = true;
    mpEnvMapSampler = nullptr;
    mpSamplerSource = nullptr;
    mReallocate = mRebuildPrograms = mResetPending = true;
    mFrame = mUpdatedFrames = 0;
    mSupported = true;
    mHasDirectLighting = false;
    mStatus = scene ? "Initializing dynamic DDGI." : "No scene.";
    if (scene && (scene->hasGeometryType(Scene::GeometryType::Custom) || scene->hasGeometryType(Scene::GeometryType::Curve) ||
                  scene->hasGeometryType(Scene::GeometryType::SDFGrid) || scene->hasGeometryType(Scene::GeometryType::DisplacedTriangleMesh)))
    {
        mSupported = false;
        mStatus = "DDGI currently supports triangle meshes (including alpha masks). This scene contains unsupported geometry.";
    }
}

void RTXGIDDGI::onSceneUpdates(RenderContext* context, IScene::UpdateFlags flags)
{
    using U = IScene::UpdateFlags;
    // Moving geometry and lighting changes are handled by the temporal DDGI update.
    // Rebuild pipelines only when the scene's shader/geometry layout changes.
    if (is_set(flags, U::RecompileNeeded | U::GeometryChanged))
    {
        mRebuildPrograms = true;
        mResetPending = true;
    }
    if (is_set(flags, U::EnvMapChanged)) mpEnvMapSampler = nullptr;
    // Reused surface radiance must not survive changes to its geometry, material, lights or occluders.
    // Camera-only changes do not invalidate this world-space cache.
    const auto cacheChanges = U::GeometryMoved | U::MeshesChanged | U::SceneGraphChanged | U::GeometryChanged |
        U::LightsMoved | U::LightIntensityChanged | U::LightPropertiesChanged | U::LightCountChanged | U::LightCollectionChanged |
        U::MaterialsChanged | U::EmissiveMaterialsChanged | U::EnvMapChanged | U::EnvMapPropertiesChanged |
        U::RenderSettingsChanged | U::RecompileNeeded;
    if (is_set(flags, cacheChanges)) mWrcResetPending = mWorldCacheReset = true;
    // Camera motion is reprojected. Invalidate cached radiance on lighting/geometry/material edits.
    if (is_set(flags, cacheChanges | U::CameraSwitched)) mRestirResetPending = true;
    // Camera::History is reported as CameraPropertiesChanged one frame after a
    // move. It must not invalidate the history that motion vectors reproject.
    if (is_set(flags, U::CameraPropertiesChanged) && mpScene &&
        is_set(mpScene->getCamera()->getChanges(), Camera::Changes::Frustum | Camera::Changes::Aperture | Camera::Changes::FocalDistance))
        mRestirResetPending = true;
}

void RTXGIDDGI::buildRayProgram(RayProgram& ray, const char* shader, const char* entry)
{
    ProgramDesc desc;
    desc.addShaderModules(mpScene->getShaderModules());
    desc.addShaderLibrary(shader);
    desc.setMaxPayloadSize(32);
    desc.setMaxAttributeSize(mpScene->getRaytracingMaxAttributeSize());
    desc.setMaxTraceRecursionDepth(1);
    ray.table = RtBindingTable::create(2, 2, mpScene->getGeometryCount());
    ray.table->setRayGen(desc.addRayGen(entry));
    ray.table->setMiss(0, desc.addMiss("probeMiss"));
    ray.table->setMiss(1, desc.addMiss("shadowMiss"));
    if (mpScene->hasGeometryType(Scene::GeometryType::TriangleMesh))
    {
        const auto ids = mpScene->getGeometryIDs(Scene::GeometryType::TriangleMesh);
        ray.table->setHitGroup(0, ids, desc.addHitGroup("probeTriangleClosestHit", "probeTriangleAnyHit"));
        ray.table->setHitGroup(1, ids, desc.addHitGroup("", "shadowTriangleAnyHit"));
    }
    auto defines = mpScene->getSceneDefines();
    defines.add(mpSampleGenerator->getDefines());
    defines.add("PAD_RANDOM_NUMBERS", "0");
    ray.program = Program::create(mpDevice, desc, defines);
    ray.program->setTypeConformances(mpScene->getTypeConformances());
    ray.vars = nullptr;
}

void RTXGIDDGI::createPrograms()
{
    buildRayProgram(mTrace, kRayShader, "traceProbes");
    buildRayProgram(mRender, kRayShader, "render");
    buildRayProgram(mHalfGather, kRayShader, "gatherHalf");
    buildRayProgram(mRestirInitialProgram, kRayShader, "restirInitial");
    buildRayProgram(mRestirTemporalProgram, kRayShader, "restirTemporal");
    buildRayProgram(mRestirSpatialProgram, kRayShader, "restirSpatial");
    buildRayProgram(mRestirIntegrateProgram, kRayShader, "restirIntegrate");
    mWorldCacheTrace = {};
    mpWorldCacheResolve = nullptr;
    // WRC pipelines are compiled lazily and never replace the original traceProbes entry point.
    mWrcTrace = {};
    mpWrcBuild = mpWrcPrepare = mpWrcShade = mpWrcGather = nullptr;
    mWrcReallocate = true;
    mRebuildPrograms = false;
}

void RTXGIDDGI::allocateResources(RenderContext* context)
{
    if (mOptions.autoBounds)
    {
        const auto bounds = mpScene->getSceneBounds();
        const auto extent = max(bounds.extent(), float3(0.01f));
        const auto center = (bounds.minPoint + bounds.maxPoint) * 0.5f;
        // Keep scene surfaces inside the SDK's full-weight region. Its exterior
        // fade spans one probe spacing, so an inset volume darkens as density rises.
        // Add 5% of the scene extent on each side, independent of probe counts.
        mGridMin = center - extent * 0.55f;
        mGridMax = center + extent * 0.55f;
    }
    else { mGridMin = mOptions.gridMin; mGridMax = mOptions.gridMax; }
    mSpacing = (mGridMax - mGridMin) / float3(mOptions.counts - 1u);
    auto texture = [&](uint32_t width, uint32_t height)
    {
        return mpDevice->createTexture2D(width, height, ResourceFormat::RGBA32Float, mOptions.counts.y, 1, nullptr, kTextureFlags);
    };
    // SDK right-handed Y-up indexing: each array layer is an XZ plane.
    mpRayData = texture(mOptions.rays, mOptions.counts.x * mOptions.counts.z);
    mpIrradiance = texture(mOptions.counts.x * 8, mOptions.counts.z * 8);
    mpDistance = texture(mOptions.counts.x * 16, mOptions.counts.z * 16);
    mpProbeData = texture(mOptions.counts.x, mOptions.counts.z);
    mpVariability = texture(mOptions.counts.x * 8, mOptions.counts.z * 8);
    static_assert(sizeof(rtxgi::DDGIVolumeDescGPUPacked) == 128);
    mpVolume = mpDevice->createStructuredBuffer(128, 1, ResourceBindFlags::ShaderResource);
    mpDiagnostics = mpDevice->createStructuredBuffer(sizeof(uint32_t), 4, kTextureFlags);
    if (!mpBlendIrradiance)
    {
        mpRelocate = ComputePass::create(mpDevice, "RenderPasses/RTXGIDDGI/ProbeRelocation.cs.slang", "DDGIProbeRelocationCS");
        mpClassify = ComputePass::create(mpDevice, "RenderPasses/RTXGIDDGI/ProbeClassification.cs.slang", "DDGIProbeClassificationCS");
    }
    DefineList irradianceDefines = {{"RTXGI_DDGI_BLEND_RADIANCE", "1"}, {"RTXGI_DDGI_PROBE_NUM_TEXELS", "8"},
        {"RTXGI_DDGI_PROBE_NUM_INTERIOR_TEXELS", "6"}, {"RTXGI_DDGI_BLEND_RAYS_PER_PROBE", std::to_string(mOptions.rays)}};
    DefineList distanceDefines = {{"RTXGI_DDGI_BLEND_RADIANCE", "0"}, {"RTXGI_DDGI_PROBE_NUM_TEXELS", "16"},
        {"RTXGI_DDGI_PROBE_NUM_INTERIOR_TEXELS", "14"}, {"RTXGI_DDGI_BLEND_RAYS_PER_PROBE", std::to_string(mOptions.rays)}};
    mpBlendIrradiance = ComputePass::create(mpDevice, "RenderPasses/RTXGIDDGI/ProbeBlending.cs.slang", "DDGIProbeBlendingCS", irradianceDefines);
    mpBlendDistance = ComputePass::create(mpDevice, "RenderPasses/RTXGIDDGI/ProbeBlending.cs.slang", "DDGIProbeBlendingCS", distanceDefines);
    mReallocate = false;
    mWrcReallocate = true;
    mResetPending = true;
}

void RTXGIDDGI::clearHistory(RenderContext* context)
{
    for (auto texture : {mpRayData, mpIrradiance, mpDistance, mpProbeData, mpVariability})
        context->clearUAV(texture->getUAV().get(), float4(0.f));
    // SDK classification ACTIVE == 0; offsets start at zero.
    mUpdatedFrames = 0;
    context->clearUAV(mpDiagnostics->getUAV().get(), uint4(0));
    mRandom.seed(1337);
    mWrcResetPending = true;
    mResetPending = false;
}

void RTXGIDDGI::allocateWrcResources()
{
    const uint32_t rayCount = mOptions.rays * mOptions.counts.x * mOptions.counts.y * mOptions.counts.z;
    std::vector<uint32_t> typeMap(1, std::numeric_limits<uint32_t>::max());
    mWrcTypeCount = 0;
    for (const auto type : mpScene->getMaterialSystem().getMaterialTypes())
    {
        const uint32_t id = uint32_t(type);
        if (id >= typeMap.size()) typeMap.resize(size_t(id) + 1, std::numeric_limits<uint32_t>::max());
        typeMap[id] = mWrcTypeCount++;
    }
    mWrcTypeCount = std::max(mWrcTypeCount, 1u);
    // One bounded active list per material shader type. A bucket can never contain
    // more than tableSize entries; separate segments avoid a CPU prefix-sum/readback.
    mpWrcHits = mpDevice->createStructuredBuffer(64, rayCount, kTextureFlags);
    mpWrcOwners = mpDevice->createStructuredBuffer(4, mOptions.wrcTableSize, kTextureFlags);
    mpWrcKeys = mpDevice->createStructuredBuffer(32, mOptions.wrcTableSize, kTextureFlags);
    mpWrcRadiance = mpDevice->createStructuredBuffer(16, mOptions.wrcTableSize, kTextureFlags);
    mpWrcLastUpdate = mpDevice->createStructuredBuffer(4, mOptions.wrcTableSize, kTextureFlags);
    mpWrcCounters = mpDevice->createStructuredBuffer(4, 16, kTextureFlags);
    mpWrcRaySlots = mpDevice->createStructuredBuffer(4, rayCount, kTextureFlags);
    mpWrcActiveSlots = mpDevice->createStructuredBuffer(4, mOptions.wrcTableSize * mWrcTypeCount, kTextureFlags);
    mpWrcActiveCounts = mpDevice->createStructuredBuffer(4, mWrcTypeCount, kTextureFlags);
    mpWrcDispatchArgs = mpDevice->createBuffer(size_t(mWrcTypeCount) * 12, kTextureFlags | ResourceBindFlags::IndirectArg);
    mpWrcTypeMap = mpDevice->createStructuredBuffer(4, uint32_t(typeMap.size()), ResourceBindFlags::ShaderResource,
        MemoryType::DeviceLocal, typeMap.data());
    mWrcAllocatedBytes = uint64_t(rayCount) * 68 + uint64_t(mOptions.wrcTableSize) * (56 + 4 * mWrcTypeCount) +
        uint64_t(mWrcTypeCount) * 16 + typeMap.size() * 4 + 64;
    mWrcReallocate = false;
    mWrcResetPending = true;
}

void RTXGIDDGI::clearWrc(RenderContext* context)
{
    context->clearUAV(mpWrcLastUpdate->getUAV().get(), uint4(0));
    context->clearUAV(mpWrcRadiance->getUAV().get(), float4(0.f));
    context->clearUAV(mpWrcCounters->getUAV().get(), uint4(0));
    context->uavBarrier(mpWrcLastUpdate.get());
    context->uavBarrier(mpWrcRadiance.get());
    mWrcResetPending = false;
    ++mWrcInvalidations;
}

void RTXGIDDGI::bindWrcProgram(RayProgram& ray, const RenderData& data)
{
    bindRayProgram(ray, data);
    bindWrcResources(ray.vars->getRootVar());
}

void RTXGIDDGI::bindWrcResources(const ShaderVar& root, uint32_t shaderBucket)
{
    root["gWrcHits"] = mpWrcHits;
    root["gWrcOwners"] = mpWrcOwners;
    root["gWrcKeys"] = mpWrcKeys;
    root["gWrcRadiance"] = mpWrcRadiance;
    root["gWrcLastUpdate"] = mpWrcLastUpdate;
    root["gWrcCounters"] = mpWrcCounters;
    root["gWrcRaySlots"] = mpWrcRaySlots;
    root["gWrcActiveSlots"] = mpWrcActiveSlots;
    root["gWrcActiveCounts"] = mpWrcActiveCounts;
    // Only prepareWRC writes this buffer. In shadeWRC it is an indirect argument,
    // so do not also bind its UAV (Falcor transitions every bound UAV).
    root["gWrcDispatchArgs"] = ref<Buffer>();
    root["gWrcTypeMap"] = mpWrcTypeMap;
    auto cb = root["WrcCB"];
    cb["gWrcTableSize"] = mOptions.wrcTableSize;
    cb["gWrcMaxAge"] = mOptions.wrcMaxAge;
    cb["gWrcFrame"] = mUpdatedFrames + 1;
    cb["gWrcCellSize"] = mOptions.wrcCellScale * std::min(mSpacing.x, std::min(mSpacing.y, mSpacing.z));
    cb["gWrcShadeSamples"] = mOptions.wrcShadeSamples;
    cb["gWrcBypassSharing"] = uint32_t(mOptions.wrcBypassSharing);
    cb["gWrcLodDistance"] = mOptions.wrcLodDistance * std::min(mSpacing.x, std::min(mSpacing.y, mSpacing.z));
    cb["gWrcMaxLod"] = mOptions.wrcMaxLod;
    cb["gWrcProbeLimit"] = mOptions.wrcProbeLimit;
    cb["gWrcTypeCount"] = mWrcTypeCount;
    cb["gWrcGroupByMaterial"] = uint32_t(mOptions.wrcGroupByMaterial);
    cb["gWrcStressMode"] = mOptions.wrcStressMode;
    cb["gWrcStressIterations"] = mOptions.wrcStressIterations;
    cb["gWrcStressStats"] = uint32_t(mOptions.wrcStressStats);
    cb["gWrcShaderBucket"] = shaderBucket;
    cb["gWrcRayCount"] = mOptions.rays * mOptions.counts.x * mOptions.counts.y * mOptions.counts.z;
}

ref<ComputePass> RTXGIDDGI::createWrcCompute(const char* entry)
{
    ProgramDesc desc;
    desc.addShaderModules(mpScene->getShaderModules());
    desc.addShaderLibrary(kWrcComputeShader).csEntry(entry);
    desc.addTypeConformances(mpScene->getTypeConformances());
    auto defines = mpScene->getSceneDefines();
    defines.add(mpSampleGenerator->getDefines());
    defines.add("PAD_RANDOM_NUMBERS", "0");
    return ComputePass::create(mpDevice, desc, defines, false);
}

void RTXGIDDGI::bindWrcCompute(RenderContext* context, const ref<ComputePass>& pass, const RenderData& data, uint32_t shaderBucket)
{
    auto program = pass->getProgram();
    bool changed = program->addDefine("USE_ANALYTIC_LIGHTS", mpScene->useAnalyticLights() ? "1" : "0");
    changed |= program->addDefine("USE_EMISSIVE_LIGHTS", mpScene->useEmissiveLights() ? "1" : "0");
    changed |= program->addDefine("USE_ENV_LIGHT", mpScene->useEnvLight() ? "1" : "0");
    changed |= program->addDefine("USE_ENV_BACKGROUND", mpScene->useEnvBackground() ? "1" : "0");
    changed |= program->addDefine("OUTPUT_INDIRECT", "0");
    changed |= program->addDefine("HAS_DIRECT_LIGHTING", "0");
    changed |= program->addDefine("is_valid_gViewW", "0");
    changed |= program->addDefine("WRC_STRESS_ENABLED", mOptions.wrcStressMode && mOptions.wrcStressIterations ? "1" : "0");
    if (changed || !pass->hasVars()) pass->setVars(ProgramVars::create(mpDevice, program.get()));
    auto root = pass->getRootVar();
    mpScene->bindShaderDataForRaytracing(context, root["gScene"], 0);
    mpSampleGenerator->bindShaderData(root);
    root["DDGIVolumes"] = mpVolume;
    root["gRayData"] = mpRayData;
    root["gIrradiance"] = mpIrradiance;
    root["gDistance"] = mpDistance;
    root["gProbeData"] = mpProbeData;
    root["gProbeSampler"] = mpSampler;
    root["gDiagnostics"] = mpDiagnostics;
    if (mpEnvMapSampler && mpScene->useEnvLight()) mpEnvMapSampler->bindShaderData(root["gEnvMapSampler"]);
    if (mpEnvMapSampler && (mpScene->useEnvLight() || mpScene->useEnvBackground()))
        root["gSafeEnvironment"] = mpEnvMapSampler->getEnvMap()->getEnvMap();
    root["PerFrameCB"]["gFrameCount"] = mFrame;
    root["PerFrameCB"]["gHistoryValid"] = mUpdatedFrames > 0;
    bindWrcResources(root, shaderBucket);
    if (pass == mpWrcPrepare) root["gWrcDispatchArgs"] = mpWrcDispatchArgs;
}

void RTXGIDDGI::traceWithWrc(RenderContext* context, const RenderData& data)
{
    if (!mWrcTrace.program)
    {
        buildRayProgram(mWrcTrace, kWrcShader, "traceWRC");
        mpWrcBuild = createWrcCompute("buildWRC");
        mpWrcPrepare = createWrcCompute("prepareWRC");
        mpWrcShade = createWrcCompute("shadeWRC");
        mpWrcGather = createWrcCompute("gatherWRC");
    }
    if (mWrcReallocate) allocateWrcResources();
    if (mWrcResetPending) clearWrc(context);
    context->clearUAV(mpWrcOwners->getUAV().get(), uint4(0xffffffffu));
    context->clearUAV(mpWrcCounters->getUAV().get(), uint4(0));
    context->clearUAV(mpWrcActiveCounts->getUAV().get(), uint4(0));
    context->uavBarrier(mpWrcOwners.get());
    context->uavBarrier(mpWrcCounters.get());
    context->uavBarrier(mpWrcActiveCounts.get());
    const uint3 dimensions(mOptions.rays, mOptions.counts.x * mOptions.counts.z, mOptions.counts.y);
    const uint32_t rayCount = mOptions.rays * mOptions.counts.x * mOptions.counts.y * mOptions.counts.z;
    // Match the linear indexing in buildWRC/gatherWRC without exceeding D3D12's
    // 65535 thread groups per dimension at the largest supported probe grid.
    constexpr uint32_t linearWidth = 65535u * 64u;
    const uint3 linearDimensions(std::min(rayCount, linearWidth), (rayCount + linearWidth - 1u) / linearWidth, 1u);
    {
        FALCOR_PROFILE(context, "WRCTrace");
        bindWrcProgram(mWrcTrace, data);
        mpScene->raytrace(context, mWrcTrace.program.get(), mWrcTrace.vars, dimensions);
    }
    context->uavBarrier(mpWrcHits.get());
    context->uavBarrier(mpRayData.get());
    context->uavBarrier(mpWrcCounters.get());
    {
        FALCOR_PROFILE(context, "WRCBuild");
        bindWrcCompute(context, mpWrcBuild, data);
        mpWrcBuild->execute(context, linearDimensions);
    }
    for (const auto& buffer : {mpWrcOwners, mpWrcRaySlots, mpWrcActiveSlots, mpWrcActiveCounts, mpWrcCounters})
        context->uavBarrier(buffer.get());
    {
        FALCOR_PROFILE(context, "WRCPrepare");
        bindWrcCompute(context, mpWrcPrepare, data);
        mpWrcPrepare->execute(context, uint3(getWrcDispatchCount(), 1, 1));
    }
    context->uavBarrier(mpWrcDispatchArgs.get());
    {
        FALCOR_PROFILE(context, "WRCShade");
        for (uint32_t bucket = 0; bucket < getWrcDispatchCount(); ++bucket)
        {
            bindWrcCompute(context, mpWrcShade, data, bucket);
            // One record per material type, or one mixed list when grouping is disabled.
            mpWrcShade->executeIndirect(context, mpWrcDispatchArgs.get(), uint64_t(bucket) * 12);
        }
    }
    context->uavBarrier(mpWrcKeys.get());
    context->uavBarrier(mpWrcRadiance.get());
    context->uavBarrier(mpWrcLastUpdate.get());
    context->uavBarrier(mpWrcCounters.get());
    context->uavBarrier(mpDiagnostics.get());
    {
        FALCOR_PROFILE(context, "WRCGather");
        bindWrcCompute(context, mpWrcGather, data);
        mpWrcGather->execute(context, linearDimensions);
    }
    context->uavBarrier(mpWrcCounters.get());
}

void RTXGIDDGI::drawWrcCells(RenderContext* context, const ref<Texture>& color)
{
    if (!mOptions.showWrcCells || !mOptions.useWRC || mOptions.wrcBypassSharing || !mUpdatedFrames ||
        mWrcReallocate || mWrcResetPending || !mpWrcKeys || !mpWrcDebugDepth) return;
    FALCOR_PROFILE(context, "WRCCellOverlay");
    if (!mpWrcDebugDraw)
    {
        mpWrcDebugPrepare = ComputePass::create(mpDevice, kWrcDebugShader, "prepareDebug");
        mpWrcDebugDraw = RasterPass::create(mpDevice, kWrcDebugShader, "vsMain", "psMain");
        auto state = mpWrcDebugDraw->getState();
        state->setVao(Vao::create(Vao::Topology::LineList));
        state->setRasterizerState(RasterizerState::create(RasterizerState::Desc().setCullMode(RasterizerState::CullMode::None)));
        state->setDepthStencilState(DepthStencilState::create(DepthStencilState::Desc().setDepthEnabled(false).setDepthWriteMask(false)));
        BlendState::Desc blend;
        blend.setRtBlend(0, true).setRtParams(0, BlendState::BlendOp::Add, BlendState::BlendOp::Add,
            BlendState::BlendFunc::SrcAlpha, BlendState::BlendFunc::OneMinusSrcAlpha,
            BlendState::BlendFunc::Zero, BlendState::BlendFunc::One);
        state->setBlendState(BlendState::create(blend));
        mpWrcDebugFbo = Fbo::create(mpDevice);
    }
    if (!mpWrcDebugArgs || mpWrcDebugArgs->getSize() != size_t(mWrcTypeCount) * 16)
        mpWrcDebugArgs = mpDevice->createBuffer(size_t(mWrcTypeCount) * 16, kTextureFlags | ResourceBindFlags::IndirectArg);
    auto prepare = mpWrcDebugPrepare->getRootVar();
    prepare["gActiveCounts"] = mpWrcActiveCounts;
    prepare["gDrawArgs"] = mpWrcDebugArgs;
    prepare["DebugCB"]["gTypeCount"] = getWrcDispatchCount();
    prepare["DebugCB"]["gTableSize"] = mOptions.wrcTableSize;
    mpWrcDebugPrepare->execute(context, uint3(getWrcDispatchCount(), 1, 1));
    context->uavBarrier(mpWrcDebugArgs.get());
    context->uavBarrier(mpWrcDebugDepth.get());
    mpWrcDebugFbo->attachColorTarget(color, 0);
    mpWrcDebugDraw->getState()->setFbo(mpWrcDebugFbo);
    auto root = mpWrcDebugDraw->getRootVar();
    root["gKeys"] = mpWrcKeys;
    root["gActiveSlots"] = mpWrcActiveSlots;
    root["gSurfaceDistance"] = mpWrcDebugDepth;
    auto cb = root["DebugCB"];
    cb["gViewProj"] = mpScene->getCamera()->getViewProjMatrix();
    cb["gCameraPosition"] = mpScene->getCamera()->getPosition();
    cb["gBaseCellWidth"] = mOptions.wrcCellScale * std::min(mSpacing.x, std::min(mSpacing.y, mSpacing.z));
    cb["gTableSize"] = mOptions.wrcTableSize;
    cb["gLodFilter"] = mOptions.wrcCellsLod;
    cb["gXRay"] = mOptions.wrcCellsXRay;
    cb["gOpacity"] = mOptions.wrcCellsOpacity;
    for (uint32_t bucket = 0; bucket < getWrcDispatchCount(); ++bucket)
    {
        cb["gBucket"] = bucket;
        context->drawIndirect(mpWrcDebugDraw->getState().get(), mpWrcDebugDraw->getVars().get(),
            1, mpWrcDebugArgs.get(), uint64_t(bucket) * 16, nullptr, 0);
    }
}

void RTXGIDDGI::uploadConstants()
{
    rtxgi::DDGIVolumeDescGPU volume = {};
    const auto center = (mGridMin + mGridMax) * 0.5f;
    const float scale = std::min(mSpacing.x, std::min(mSpacing.y, mSpacing.z));
    volume.origin = {center.x, center.y, center.z};
    volume.rotation = {0.f, 0.f, 0.f, 1.f};
    std::uniform_real_distribution<float> uniform(0.f, 1.f);
    const float a = uniform(mRandom), b = 6.28318530718f * uniform(mRandom), c = 6.28318530718f * uniform(mRandom);
    volume.probeRayRotation = {std::sqrt(1.f - a) * std::sin(b), std::sqrt(1.f - a) * std::cos(b),
                               std::sqrt(a) * std::sin(c), std::sqrt(a) * std::cos(c)};
    volume.probeSpacing = {mSpacing.x, mSpacing.y, mSpacing.z};
    volume.probeCounts = {int(mOptions.counts.x), int(mOptions.counts.y), int(mOptions.counts.z)};
    volume.probeNumRays = int(mOptions.rays);
    volume.probeNumIrradianceInteriorTexels = 6;
    volume.probeNumDistanceInteriorTexels = 14;
    // Bootstrap an empty volume without applying a long steady-state history.
    volume.probeHysteresis = std::min(mOptions.hysteresis, float(mUpdatedFrames) / float(mUpdatedFrames + 1u));
    volume.probeMaxRayDistance = std::max(length(mGridMax - mGridMin) * 2.f, 1.f);
    volume.probeNormalBias = mOptions.normalBias * scale;
    volume.probeViewBias = mOptions.viewBias * scale;
    volume.probeDistanceExponent = 50.f;
    volume.probeIrradianceEncodingGamma = 5.f;
    volume.probeIrradianceThreshold = 0.25f;
    volume.probeBrightnessThreshold = mUpdatedFrames < 32 ? std::numeric_limits<float>::max() : 0.10f;
    volume.probeRandomRayBackfaceThreshold = 0.10f;
    volume.probeFixedRayBackfaceThreshold = 0.25f;
    volume.probeMinFrontfaceDistance = mOptions.minFrontfaceDistance * scale;
    volume.probeRayDataFormat = 6; // SDK F32x4
    volume.probeIrradianceFormat = 6;
    volume.probeRelocationEnabled = mOptions.relocation;
    volume.probeClassificationEnabled = mOptions.classification;
    volume.probeVariabilityEnabled = false;
    const auto packed = rtxgi::PackDDGIVolumeDescGPU(volume);
    mpVolume->setBlob(&packed, 0, sizeof(packed));
}

void RTXGIDDGI::bindRayProgram(RayProgram& ray, const RenderData& data)
{
    bool changed = ray.program->addDefine("LUMEN_WORLD_CACHE", mOptions.worldCache ? "1" : "0");
    changed |= ray.program->addDefine("USE_ANALYTIC_LIGHTS", mpScene->useAnalyticLights() ? "1" : "0");
    changed |= ray.program->addDefine("USE_EMISSIVE_LIGHTS", mpScene->useEmissiveLights() ? "1" : "0");
    changed |= ray.program->addDefine("USE_ENV_LIGHT", mpScene->useEnvLight() ? "1" : "0");
    changed |= ray.program->addDefine("USE_ENV_BACKGROUND", mpScene->useEnvBackground() ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_INDIRECT", data.getTexture("indirect") ? "1" : "0");
    changed |= ray.program->addDefine("is_valid_gViewW", data.getTexture("viewW") ? "1" : "0");
    changed |= ray.program->addDefine("HAS_DIRECT_LIGHTING", data.getTexture("directLighting") ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_GATHER_DIFFUSE", data.getTexture("gatherDiffuse") ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_GATHER_SPECULAR", data.getTexture("gatherSpecular") ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_DIFFUSERADIANCEHITDIST", data.getTexture("diffuseRadianceHitDist") ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_SPECULARRADIANCEHITDIST", data.getTexture("specularRadianceHitDist") ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_DIFFUSEREFLECTANCE", data.getTexture("diffuseReflectance") ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_SPECULARREFLECTANCE", data.getTexture("specularReflectance") ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_UNFILTEREDCOLOR", data.getTexture("unfilteredColor") ? "1" : "0");
    changed |= ray.program->addDefine("SPLIT_HALF_GATHER",
        mOptions.finalGather && mOptions.halfResolutionGather && !mOptions.showWrcCells ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_RESTIR_DEBUG", data.getTexture("restirDebug") ? "1" : "0");
    changed |= ray.program->addDefine("RESTIR_MOTION", data.getTexture("mvec") ? "1" : "0");
    changed |= ray.program->addDefine("RESTIR_GATHER", restirActive() ? "1" : "0");
    if (changed) ray.vars = nullptr;
    if (!ray.vars)
    {
        ray.vars = RtProgramVars::create(mpDevice, ray.program, ray.table);
        mpSampleGenerator->bindShaderData(ray.vars->getRootVar());
    }
    auto root = ray.vars->getRootVar();
    if (mOptions.worldCache) bindWorldCache(root);
    root["DDGIVolumes"] = mpVolume;
    root["gRayData"] = mpRayData;
    root["gIrradiance"] = mpIrradiance;
    root["gDistance"] = mpDistance;
    root["gProbeData"] = mpProbeData;
    root["gProbeSampler"] = mpSampler;
    root["gDiagnostics"] = mpDiagnostics;
    if (mpEnvMapSampler && mpScene->useEnvLight()) mpEnvMapSampler->bindShaderData(root["gEnvMapSampler"]);
    if (mpEnvMapSampler && (mpScene->useEnvLight() || mpScene->useEnvBackground()))
        root["gSafeEnvironment"] = mpEnvMapSampler->getEnvMap()->getEnvMap();
    if (restirActive())
    {
        root["gReservoirHistory"] = mpRestirHistory;
        root["gReservoirInput"] = mpRestirInput;
        root["gReservoirOutput"] = mpRestirOutput;
        root["gReservoirTemporal"] = mpRestirTemporal;
        if (data.getTexture("mvec")) root["gMotionVectors"] = data.getTexture("mvec");
        if (data.getTexture("restirDebug")) root["gRestirDebug"] = data.getTexture("restirDebug");
    }
    root["gVBuffer"] = data.getTexture("vbuffer");
    root["gViewW"] = data.getTexture("viewW");
    if (data.getTexture("directLighting")) root["gDirectLighting"] = data.getTexture("directLighting");
    root["gOutputColor"] = data.getTexture("color");
    root["gWrcDebugDepth"] = mpWrcDebugDepth;
    if (data.getTexture("indirect")) root["gOutputIndirect"] = data.getTexture("indirect");
    if (data.getTexture("gatherDiffuse")) root["gOutputGatherDiffuse"] = data.getTexture("gatherDiffuse");
    if (data.getTexture("gatherSpecular")) root["gOutputGatherSpecular"] = data.getTexture("gatherSpecular");
    if (data.getTexture("diffuseRadianceHitDist")) root["gDiffuseRadianceHitDist"] = data.getTexture("diffuseRadianceHitDist");
    if (data.getTexture("specularRadianceHitDist")) root["gSpecularRadianceHitDist"] = data.getTexture("specularRadianceHitDist");
    if (data.getTexture("diffuseReflectance")) root["gDiffuseReflectance"] = data.getTexture("diffuseReflectance");
    if (data.getTexture("specularReflectance")) root["gSpecularReflectance"] = data.getTexture("specularReflectance");
    if (data.getTexture("unfilteredColor")) root["gUnfilteredColor"] = data.getTexture("unfilteredColor");
    auto cb = root["PerFrameCB"];
    cb["gFrameCount"] = mFrame;
    cb["gFrameDim"] = data.getDefaultTextureDims();
    cb["gAdjustPrimaryShadingNormals"] = data.getDictionary().getValue(kRenderPassGBufferAdjustShadingNormals, false);
    cb["gFinalGather"] = mOptions.finalGather;
    cb["gHalfResolutionGather"] = mOptions.halfResolutionGather;
    cb["gGatherOffset"] = mGatherOffset;
    cb["gRestirHistoryLength"] = mOptions.restirHistoryLength;
    cb["gRestirMaxAge"] = mOptions.restirMaxAge;
    cb["gRestirTemporalCellMapping"] = mOptions.restirTemporalCellMapping;
    cb["gRestirDim"] = mRestirDim;
    cb["gRestirPreviousViewProj"] = mRestirPreviousViewProj;
    cb["gRestirPreviousOffset"] = mRestirPreviousOffset;
    cb["gRestirHistoryValid"] = mRestirHistoryValid && mOptions.restirTemporal;
    cb["gRestirSpatialSamples"] = mOptions.restirSpatialSamples;
    cb["gRestirBiasCorrection"] = mOptions.restirBiasCorrection;
    cb["gRestirIntegrateSamples"] = mOptions.restirIntegrateSamples;
    cb["gRestirSpatialRadius"] = mOptions.restirSpatialRadius;
    cb["gRestirSpatialPassIndex"] = mRestirSpatialPassIndex;
    cb["gRestirIntegrateRadius"] = mOptions.restirIntegrateRadius;
    cb["gRestirFullResolution"] = mOptions.restirFullResolution;
    cb["gGatherDiffuse"] = mOptions.gatherDiffuse;
    cb["gGatherSpecular"] = mOptions.gatherSpecular;
    cb["gEnableGI"] = mOptions.enableGI;
    cb["gIndirectOnly"] = mOptions.indirectOnly;
    cb["gUseRTXDI"] = mOptions.useRTXDI;
    cb["gShowWrcCells"] = bool(mpWrcDebugDepth) && (mOptions.showProbes || (mOptions.showWrcCells && mOptions.useWRC && !mOptions.wrcBypassSharing));
    cb["gHistoryValid"] = mUpdatedFrames > 0;
    cb["gIntensity"] = mOptions.intensity;
    cb["gProbeRadius"] = std::min(mSpacing.x, std::min(mSpacing.y, mSpacing.z)) * 0.08f;
}

void RTXGIDDGI::updateProbes(RenderContext* context)
{
    const auto bind = [&](const ref<ComputePass>& pass)
    {
        auto root = pass->getRootVar();
        root["DDGI"]["volumeIndex"] = 0u;
        root["DDGIVolumes"] = mpVolume;
        root["RayData"] = mpRayData;
        root["ProbeData"] = mpProbeData;
        return root;
    };
    auto irradiance = bind(mpBlendIrradiance);
    irradiance["Output"] = mpIrradiance;
    irradiance["ProbeVariability"] = mpVariability;
    mpBlendIrradiance->execute(context, uint3(mOptions.counts.x * 8, mOptions.counts.z * 8, mOptions.counts.y));
    auto distance = bind(mpBlendDistance);
    distance["Output"] = mpDistance;
    mpBlendDistance->execute(context, uint3(mOptions.counts.x * 16, mOptions.counts.z * 16, mOptions.counts.y));
    context->uavBarrier(mpIrradiance.get());
    context->uavBarrier(mpDistance.get());
    const uint32_t count = mOptions.counts.x * mOptions.counts.y * mOptions.counts.z;
    if (mOptions.relocation)
    {
        bind(mpRelocate);
        mpRelocate->execute(context, uint3(count, 1, 1));
        context->uavBarrier(mpProbeData.get());
    }
    if (mOptions.classification)
    {
        bind(mpClassify);
        mpClassify->execute(context, uint3(count, 1, 1));
        context->uavBarrier(mpProbeData.get());
    }
    ++mUpdatedFrames;
}

void RTXGIDDGI::execute(RenderContext* context, const RenderData& data)
{
    // Quantized Hammersley(i, 8) in a 2x2 block: all four phases occur twice.
    const uint2 dim = data.getDefaultTextureDims();
    mGatherOffset = mOptions.finalGather && mOptions.halfResolutionGather && mOptions.jitterHalfGather
        ? min(uint2((mFrame & 7u) >> 2u, mFrame & 1u), dim - uint2(1)) : uint2(0);
    data.getDictionary()["RTXGIDDGI.gatherOffset"] = mGatherOffset;
    mHasDirectLighting = data.getTexture("directLighting") != nullptr;
    if (!mpScene || !mSupported)
    {
        for (const auto& output : kOutputs)
            if (auto texture = data.getTexture(output.name)) context->clearTexture(texture.get());
        return;
    }
    if (auto debug = data.getTexture("restirDebug")) context->clearTexture(debug.get());
    if (restirActive())
    {
        uint2 reservoirDim = mOptions.halfResolutionGather ? (dim + uint2(1)) / uint2(2) : dim;
        if (!mpRestirHistory || any(mRestirDim != reservoirDim))
        {
            mRestirDim = reservoirDim;
            const uint32_t count = reservoirDim.x * reservoirDim.y;
            mpRestirInitial = mpDevice->createStructuredBuffer(96, count, kTextureFlags);
            mpRestirTemporal = mpDevice->createStructuredBuffer(96, count, kTextureFlags);
            mpRestirSpatial = mpDevice->createStructuredBuffer(96, count, kTextureFlags);
            mpRestirHistory = mpDevice->createStructuredBuffer(96, count, kTextureFlags);
            mRestirResetPending = true;
        }
        if (mRestirResetPending || mResetPending || mReallocate || mOptionsChanged)
        {
            mRestirHistoryValid = false;
            mRestirResetPending = false;
            ++mRestirResetCount;
        }
        mpRestirInput = mpRestirInitial;
        mpRestirOutput = mpRestirInitial;
    }
    else
    {
        mpRestirInitial = mpRestirTemporal = mpRestirSpatial = mpRestirHistory = nullptr;
        mpRestirInput = mpRestirOutput = nullptr;
        mRestirInitialProgram.vars = mRestirTemporalProgram.vars = mRestirSpatialProgram.vars = mRestirIntegrateProgram.vars = nullptr;
        mRestirHistoryValid = false;

    }
    if (mOptionsChanged || mResetPending || mReallocate)
    {
        auto& dictionary = data.getDictionary();
        dictionary[kRenderPassRefreshFlags] = dictionary.getValue(kRenderPassRefreshFlags, RenderPassRefreshFlags::None) |
                                              RenderPassRefreshFlags::RenderOptionsChanged;
        mOptionsChanged = false;
    }
    if (mpScene->getRenderSettings().useEmissiveLights) mpScene->getLightCollection(context);
    if ((mpScene->useEnvLight() || mpScene->useEnvBackground()) &&
        (!mpEnvMapSampler || mpSamplerSource != mpScene->getEnvMap()))
    {
        mpSamplerSource = mpScene->getEnvMap();
        auto source = mpSamplerSource->getEnvMap();
        auto safeTexture = mpDevice->createTexture2D(source->getWidth(), source->getHeight(), ResourceFormat::RGBA32Float,
            1, 1, nullptr, kTextureFlags);
        auto sanitize = ComputePass::create(mpDevice, "RenderPasses/RTXGIDDGI/SanitizeEnvironment.cs.slang", "main");
        sanitize->getRootVar()["gSource"] = source;
        sanitize->getRootVar()["gDestination"] = safeTexture;
        sanitize->execute(context, source->getWidth(), source->getHeight());
        // Some HDR assets contain Inf/negative pixels. A single Inf can poison
        // every level of an importance hierarchy, even if ray output is guarded.
        mpEnvMapSampler = std::make_unique<EnvMapSampler>(mpDevice, EnvMap::create(mpDevice, safeTexture));
    }
    if (mRebuildPrograms) createPrograms();
    if (mOptions.worldCache) prepareWorldCache(context);
    else
    {
        if (mReallocate) allocateResources(context);
        if (mResetPending) clearHistory(context);
        uploadConstants();
    }
    if (mOptions.worldCache && mOptions.update) updateWorldCache(context, data);
    if (!mOptions.worldCache && mOptions.update)
    {
        FALCOR_PROFILE(context, "ProbeUpdate");
        if (mOptions.useWRC) traceWithWrc(context, data);
        else
        {
            FALCOR_PROFILE(context, "OriginalTrace");
            bindRayProgram(mTrace, data);
            mpScene->raytrace(context, mTrace.program.get(), mTrace.vars,
                              uint3(mOptions.rays, mOptions.counts.x * mOptions.counts.z, mOptions.counts.y));
        }
        context->uavBarrier(mpRayData.get());
        {
            FALCOR_PROFILE(context, "SDKUpdate");
            updateProbes(context);
        }
    }
    if (mOptions.showProbes || (mOptions.showWrcCells && mOptions.useWRC && !mOptions.wrcBypassSharing))
    {
        const auto size = data.getDefaultTextureDims();
        if (!mpWrcDebugDepth || mpWrcDebugDepth->getWidth() != size.x || mpWrcDebugDepth->getHeight() != size.y)
            mpWrcDebugDepth = mpDevice->createTexture2D(size.x, size.y, ResourceFormat::R32Float, 1, 1, nullptr, kTextureFlags);
    }
    bindRayProgram(mRender, data);
    const uint2 frameDim = data.getDefaultTextureDims();
    const bool splitGather = !restirActive() && mOptions.finalGather && mOptions.halfResolutionGather && !mOptions.showWrcCells;
    {
        FALCOR_PROFILE(context, "PrimaryShading");
        mpScene->raytrace(context, mRender.program.get(), mRender.vars, uint3(frameDim, 1));
    }
    if (splitGather)
    {
        FALCOR_PROFILE(context, "HalfGather");
        // Preserve diagnostic outputs and order the sparse color read-modify-write.
        for (const auto& output : kOutputs)
            if (auto texture = data.getTexture(output.name)) context->uavBarrier(texture.get());
        bindRayProgram(mHalfGather, data);
        mpScene->raytrace(context, mHalfGather.program.get(), mHalfGather.vars, uint3(max(frameDim / uint2(2), uint2(1)), 1));
    }
    if (restirActive())
    {
        const auto dispatch = [&](RayProgram& program, const ref<Buffer>& input, const ref<Buffer>& output, uint2 size)
        {
            mpRestirInput = input; mpRestirOutput = output;
            if (input) context->uavBarrier(input.get());
            bindRayProgram(program, data);
            mpScene->raytrace(context, program.program.get(), program.vars, uint3(size, 1));
            if (output) context->uavBarrier(output.get());
        };
        { FALCOR_PROFILE(context, "ReSTIRInitial");
          dispatch(mRestirInitialProgram, mpRestirInitial, mpRestirInitial, mRestirDim); }
        { FALCOR_PROFILE(context, "ReSTIRTemporal");
          dispatch(mRestirTemporalProgram, mpRestirInitial, mpRestirTemporal, mRestirDim); }
        ref<Buffer> integratedReservoirs = mpRestirTemporal;
        if (mOptions.restirSpatial)
        {
            FALCOR_PROFILE(context, "ReSTIRSpatial");
            for (uint32_t pass = 0; pass < mOptions.restirSpatialPasses; ++pass)
            {
                mRestirSpatialPassIndex = pass;
                // Initial candidates are dead after temporal resampling; reuse
                // their storage as the second spatial ping-pong buffer.
                auto destination = (pass & 1u) ? mpRestirInitial : mpRestirSpatial;
                dispatch(mRestirSpatialProgram, integratedReservoirs, destination, mRestirDim);
                integratedReservoirs = destination;
            }
        }
        { FALCOR_PROFILE(context, "ReSTIRIntegrate");
          for (const auto& output : kOutputs)
              if (auto texture = data.getTexture(output.name)) context->uavBarrier(texture.get());
          dispatch(mRestirIntegrateProgram, integratedReservoirs, nullptr, mOptions.restirFullResolution ? dim : mRestirDim); }
        // NVIDIA's separate temporal+spatial pipeline retains the final spatial
        // result. Keep the temporal-only feedback available for controlled audits.
        // Swap the owning member (not the local alias), preserving four distinct buffers.
        if (mOptions.restirSpatialFeedback && mOptions.restirSpatial)
        {
            if (integratedReservoirs == mpRestirInitial) std::swap(mpRestirInitial, mpRestirHistory);
            else std::swap(mpRestirSpatial, mpRestirHistory);
        }
        else std::swap(mpRestirTemporal, mpRestirHistory);
        mRestirPreviousViewProj = mpScene->getCamera()->getViewProjMatrix();
        mRestirPreviousOffset = mGatherOffset;
        mRestirHistoryValid = true;
    }
    drawWrcCells(context, data.getTexture("color"));
    drawProbeVisualization(context, data);
    mStatus = mOptions.update ? (mOptions.useWRC ? "Updating probes via active WRC cells." : "Updating probes with original per-ray shading.") :
        "Probe updates frozen; camera and direct light remain live.";
    if (mOptions.worldCache) mStatus = "WorldCache: independent diffuse surface radiance; no DDGI probe updates.";
    ++mFrame;
}

Properties RTXGIDDGI::getStats() const
{
    Properties stats;
    stats["worldCache"] = mOptions.worldCache;
    stats["worldCacheUpdates"] = mWorldCacheFrames;
    if (mOptions.worldCache && mpWCStats)
    {
        uint32_t counters[4] = {};
        mpWCStats->getBlob(counters, 0, sizeof(counters));
        stats["cacheLookups"] = counters[0]; stats["cacheHits"] = counters[1];
        stats["cacheInsertionFailures"] = counters[2]; stats["cacheOccupied"] = counters[3];
    }
    stats["updatedFrames"] = mUpdatedFrames;
    const bool allocated = mpProbeData && !mReallocate && mpScene && mSupported;
    stats["totalProbes"] = allocated ? mOptions.counts.x * mOptions.counts.y * mOptions.counts.z : 0u;
    stats["status"] = mStatus;
    stats["supported"] = mSupported;
    stats["usingRTXDI"] = mHasDirectLighting && mOptions.useRTXDI && !mOptions.finalGather;
    stats["finalGather"] = mOptions.finalGather;
    stats["restirGather"] = mOptions.restirGather;
    stats["restirHistoryLength"] = mOptions.restirHistoryLength;
    stats["restirMaxAge"] = mOptions.restirMaxAge;
    stats["restirFullResolution"] = mOptions.restirFullResolution;
    stats["restirSpatialPasses"] = mOptions.restirSpatialPasses;
    stats["restirSpatialFeedback"] = mOptions.restirSpatialFeedback;
    stats["restirTemporalCellMapping"] = mOptions.restirTemporalCellMapping;
    stats["restirIntegrateSamples"] = mOptions.restirIntegrateSamples;
    stats["restirAllocatedBytes"] = restirActive() ? uint64_t(mRestirDim.x) * mRestirDim.y * 96u * 4u : 0ull;
    stats["restirResetCount"] = mRestirResetCount;
    stats["gridMin"] = mGridMin;
    stats["gridMax"] = mGridMax;
    stats["wrcEnabled"] = mOptions.useWRC;
    stats["wrcGroupByMaterial"] = mOptions.wrcGroupByMaterial;
    stats["wrcStressMode"] = mOptions.wrcStressMode;
    stats["wrcStressIterations"] = mOptions.wrcStressIterations;
    stats["showWrcCells"] = mOptions.showWrcCells;
    stats["wrcCellsLod"] = mOptions.wrcCellsLod;
    stats["wrcCellSize"] = mOptions.wrcCellScale * std::min(mSpacing.x, std::min(mSpacing.y, mSpacing.z));
    stats["wrcTableSize"] = mOptions.wrcTableSize;
    stats["wrcLodDistance"] = mOptions.wrcLodDistance * std::min(mSpacing.x, std::min(mSpacing.y, mSpacing.z));
    stats["wrcProbeLimit"] = mOptions.wrcProbeLimit;
    stats["wrcInvalidations"] = mWrcInvalidations;
    stats["wrcAllocatedBytes"] = mWrcAllocatedBytes;
    uint32_t wrcCounters[16] = {};
    uint32_t activeEntries = 0, shaderGroups = 0, scheduledThreads = 0;
    if (mOptions.useWRC && mpWrcCounters && !mWrcReallocate && !mWrcResetPending)
    {
        mpWrcCounters->getBlob(wrcCounters, 0, sizeof(wrcCounters));
        const uint32_t dispatchCount = getWrcDispatchCount();
        std::vector<uint32_t> counts(dispatchCount), args(size_t(dispatchCount) * 3);
        mpWrcActiveCounts->getBlob(counts.data(), 0, counts.size() * sizeof(uint32_t));
        mpWrcDispatchArgs->getBlob(args.data(), 0, args.size() * sizeof(uint32_t));
        for (uint32_t i = 0; i < dispatchCount; ++i)
        {
            activeEntries += counts[i];
            shaderGroups += counts[i] != 0 ? 1u : 0u;
            scheduledThreads += args[size_t(i) * 3] * 64;
        }
    }
    stats["wrcValidRays"] = wrcCounters[0];
    stats["wrcOccupiedEntries"] = wrcCounters[1];
    stats["wrcShadedEntries"] = wrcCounters[2];
    stats["wrcServedRays"] = wrcCounters[3];
    stats["wrcFallbackRays"] = wrcCounters[4];
    stats["wrcTemporalReusedEntries"] = wrcCounters[5];
    stats["wrcNonFiniteResults"] = wrcCounters[6];
    stats["wrcShadeEvaluations"] = uint64_t(wrcCounters[2]) * mOptions.wrcShadeSamples + wrcCounters[4];
    stats["wrcProbeSteps"] = wrcCounters[7];
    stats["wrcProbeLimitFailures"] = wrcCounters[8];
    stats["wrcMaxLod"] = wrcCounters[9];
    stats["wrcLodRays"] = wrcCounters[10];
    stats["wrcCrossPrimitiveServedRays"] = wrcCounters[11];
    stats["wrcWaveTypeSum"] = wrcCounters[12];
    stats["wrcWaveCount"] = wrcCounters[13];
    stats["wrcStressChecksum"] = wrcCounters[14];
    stats["wrcStressEntries"] = wrcCounters[15];
    stats["wrcActiveEntries"] = activeEntries;
    stats["wrcShaderGroups"] = shaderGroups;
    stats["wrcMaterialTypes"] = mWrcTypeCount;
    stats["wrcDispatches"] = mOptions.useWRC && mpWrcCounters && !mWrcReallocate && !mWrcResetPending ? getWrcDispatchCount() : 0u;
    stats["wrcScheduledThreads"] = scheduledThreads;
    uint32_t active = 0, relocated = 0, nonFinite = 0;
    float maximum = 0.f;
    // Explicit diagnostic readback only. No GPU/CPU synchronization in normal rendering.
    if (allocated)
    {
        auto context = mpDevice->getRenderContext();
        for (uint32_t layer = 0; layer < mOptions.counts.y; ++layer)
        {
            const auto bytes = context->readTextureSubresource(mpProbeData.get(), layer);
            for (size_t offset = 0; offset + sizeof(float4) <= bytes.size(); offset += sizeof(float4))
            {
                float4 value;
                std::memcpy(&value, bytes.data() + offset, sizeof(value));
                if (!all(isfinite(value))) ++nonFinite;
                if (value.w < 0.5f) ++active;
                if (dot(value.xyz(), value.xyz()) > 1e-12f) ++relocated;
            }
            const auto irradiance = context->readTextureSubresource(mpIrradiance.get(), layer);
            for (size_t offset = 0; offset + sizeof(float4) <= irradiance.size(); offset += sizeof(float4))
            {
                float4 value;
                std::memcpy(&value, irradiance.data() + offset, sizeof(value));
                if (!all(isfinite(value))) ++nonFinite;
                maximum = std::max(maximum, std::max(value.x, std::max(value.y, value.z)));
            }
            for (auto texture : {mpRayData, mpDistance})
            {
                const auto values = context->readTextureSubresource(texture.get(), layer);
                for (size_t offset = 0; offset + sizeof(float4) <= values.size(); offset += sizeof(float4))
                {
                    float4 value;
                    std::memcpy(&value, values.data() + offset, sizeof(value));
                    if (!all(isfinite(value))) ++nonFinite;
                }
            }
        }
    }
    if (mOptions.worldCache && mpWCLighting && !mWorldCacheReset)
    {
        std::vector<float4> lighting(1u << 20);
        mpWCLighting->getBlob(lighting.data(), 0, lighting.size() * sizeof(float4));
        for (const auto& value : lighting) if (!all(isfinite(value))) ++nonFinite;
    }
    if (mpDiagnostics)
    {
        uint32_t diagnostics[4] = {};
        mpDiagnostics->getBlob(diagnostics, 0, sizeof(diagnostics));
        stats["rejectedMaterialSamples"] = diagnostics[0];
        stats["rejectedDirectSamples"] = diagnostics[1];
        stats["rejectedHistorySamples"] = diagnostics[2];
        stats["rejectedRaySamples"] = diagnostics[3];
    }
    stats["activeProbes"] = active;
    stats["relocatedProbes"] = relocated;
    stats["finite"] = nonFinite == 0;
    stats["nonFiniteTexels"] = nonFinite;
    stats["irradianceMax"] = maximum;
    return stats;
}

void RTXGIDDGI::renderUI(Gui::Widgets& widgets)
{
    if (mOptions.worldCache) { renderWorldCacheUI(widgets); return; }
    widgets.text("NVIDIA RTXGI-DDGI 1.3.7 | dynamic diffuse GI");
    widgets.text(mStatus);
    widgets.text("Probe updates: " + std::to_string(mUpdatedFrames));
    Properties p;
    auto options = mOptions;
    if (widgets.checkbox("Update probes", options.update)) p["updateEnabled"] = options.update;
    if (widgets.button("Reset history")) reset();
    if (widgets.checkbox("Enable DDGI", options.enableGI)) p["enableGI"] = options.enableGI;
    if (auto gather = widgets.group("Final gather", true))
    {
        if (gather.checkbox("Enabled", options.finalGather)) p["finalGather"] = options.finalGather;
        gather.tooltip("Trace diffuse and specular reflection from primary visibility. Uses internal direct lighting to avoid double-counting environment/emissive hits. No recursive specular or transmission.");
        uint32_t gatherResolution = options.halfResolutionGather ? 0u : 1u;
        const Gui::DropdownList gatherResolutions = {{0, "Half"}, {1, "Full"}};
        if (gather.dropdown("Resolution", gatherResolutions, gatherResolution))
            p["halfResolutionGather"] = gatherResolution == 0u;
        gather.tooltip("Half traces one pixel per 2x2 block and reconstructs full-resolution lighting. Applies when final gather is enabled.");
        if (options.halfResolutionGather)
        {
            if (gather.checkbox("Jitter sample position", options.jitterHalfGather)) p["jitterHalfGather"] = options.jitterHalfGather;
            gather.tooltip("Cycle the sampled pixel within each 2x2 block over eight frames. Reconstruction follows the actual sample position. Experimental Accumulate path; leave off for NRD.");
        }
        if (options.finalGather)
        {
            if (gather.checkbox("ReSTIR gather (experimental)", options.restirGather)) p["restirGather"] = options.restirGather;
            gather.tooltip("Uniform hemisphere candidates, reprojected temporal reservoirs and spatial resampling. Full-resolution integration and Accumulate are independent options.");
            if (options.restirGather)
            {
                if (gather.checkbox("Full-resolution integration", options.restirFullResolution)) p["restirFullResolution"] = options.restirFullResolution;
                gather.tooltip("Off: shade each reservoir at gather resolution, then use the original guided upsampler. On: evaluate multiple reservoir samples at every full-resolution pixel. Independent of temporal/spatial reuse.");
                if (gather.checkbox("Temporal reuse", options.restirTemporal)) p["restirTemporal"] = options.restirTemporal;
                if (gather.checkbox("Source visibility correction", options.restirBiasCorrection)) p["restirBiasCorrection"] = options.restirBiasCorrection;
                if (gather.checkbox("Spatial reuse", options.restirSpatial)) p["restirSpatial"] = options.restirSpatial;
                if (gather.checkbox("Spatial reservoir feedback", options.restirSpatialFeedback)) p["restirSpatialFeedback"] = options.restirSpatialFeedback;
                if (gather.var("Spatial passes", options.restirSpatialPasses, 1u, 4u)) p["restirSpatialPasses"] = options.restirSpatialPasses;
                if (gather.var("Integration radius", options.restirIntegrateRadius, 0.f, 8.f)) p["restirIntegrateRadius"] = options.restirIntegrateRadius;
                if (gather.var("Spatial samples", options.restirSpatialSamples, 0u, 16u)) p["restirSpatialSamples"] = options.restirSpatialSamples;
                if (gather.var("Integration samples", options.restirIntegrateSamples, 1u, 16u)) p["restirIntegrateSamples"] = options.restirIntegrateSamples;
                if (gather.var("Spatial radius", options.restirSpatialRadius, 1.f, 64.f)) p["restirSpatialRadius"] = options.restirSpatialRadius;
                if (gather.var("Maximum sample age (0 disables)", options.restirMaxAge, 0u, 1024u)) p["restirMaxAge"] = options.restirMaxAge;
                if (gather.var("Reservoir candidates", options.restirHistoryLength, 1u, 32u)) p["restirHistoryLength"] = options.restirHistoryLength;
                gather.tooltip("Maximum temporal candidate count. Visibility rays and full-resolution integration add cost; this is not the rays-per-pixel setting.");
            }
            if (gather.checkbox("Gather diffuse", options.gatherDiffuse)) p["gatherDiffuse"] = options.gatherDiffuse;
            if (gather.checkbox("Gather specular", options.gatherSpecular)) p["gatherSpecular"] = options.gatherSpecular;
            gather.text("RTXDI input bypassed. Toggle temporal accumulation in Accumulate > Enabled.");
        }
    }
    if (widgets.checkbox("Indirect only", options.indirectOnly)) p["indirectOnly"] = options.indirectOnly;
    if (widgets.checkbox("Use world radiance cache", options.useWRC)) p["useWRC"] = options.useWRC;
    widgets.tooltip("Distance-LOD spatial hash with bounded linear probing and GPU-driven active-cell shading. Off uses original DDGI. Switching resets probe history; let both modes converge before comparing.");
    if (options.useWRC)
    {
        if (widgets.var("Cell scale", options.wrcCellScale, 0.01f, 2.f, 0.01f)) p["wrcCellScale"] = options.wrcCellScale;
        widgets.tooltip("Base cell width as a fraction of the smallest probe spacing. Distance LOD scales this width; larger cells share more work but smooth lighting.");
        if (widgets.var("LOD dist", options.wrcLodDistance, 0.1f, 128.f, 0.1f)) p["wrcLodDistance"] = options.wrcLodDistance;
        widgets.tooltip("LOD distance in units of the smallest probe spacing. Cell scale doubles at distance, 3x distance, 7x distance, and so on.");
        const Gui::DropdownList lodScales = {{1, "1x"}, {2, "2x"}, {4, "4x"}, {8, "8x"}, {16, "16x"}, {32, "32x"}, {64, "64x"}};
        if (widgets.dropdown("Max LOD", lodScales, options.wrcMaxLod)) p["wrcMaxLod"] = options.wrcMaxLod;
        widgets.tooltip("Maximum cell-width multiplier. 1x disables distance LOD while keeping the active-list cache.");
        if (widgets.var("Hash steps", options.wrcProbeLimit, 1u, 64u)) p["wrcProbeLimit"] = options.wrcProbeLimit;
        widgets.tooltip("Maximum slots examined on a hash collision. Exhausted searches shade that ray directly.");
        if (widgets.var("Max age", options.wrcMaxAge, 0u, 8u)) p["wrcMaxAge"] = options.wrcMaxAge;
        widgets.tooltip("0 refreshes active cells every probe update. Higher values reuse radiance across updates, with slower lighting feedback. Disabled during the first 32 updates.");
        if (widgets.var("Samples", options.wrcShadeSamples, 1u, 8u)) p["wrcShadeSamples"] = options.wrcShadeSamples;
        widgets.text("Cache setting changes reset probe history.");
        if (widgets.checkbox("Group shading by material", options.wrcGroupByMaterial)) p["wrcGroupByMaterial"] = options.wrcGroupByMaterial;
        widgets.tooltip("On: one compute dispatch per material type. Off: shade all active WRC cells in one mixed dispatch. Preserves probe history; rebuilds WRC lists on the next update.");
        Gui::DropdownList stressModes = {{0, "Off"}, {1, "Common loop"}, {2, "Per-type loops"}};
        if (widgets.dropdown("Synthetic shading load", stressModes, options.wrcStressMode)) p["wrcStressMode"] = options.wrcStressMode;
        if (options.wrcStressMode)
        {
            if (widgets.var("Stress iterations", options.wrcStressIterations, 0u, 10000u)) p["wrcStressIterations"] = options.wrcStressIterations;
            widgets.tooltip("Benchmark-only integer work next to material setup. Writes a checksum to unused WRC alpha; does not change lighting.");
        }
        if (widgets.checkbox("Show WRC cells", options.showWrcCells)) p["showWrcCells"] = options.showWrcCells;
        if (options.showWrcCells)
        {
            if (widgets.checkbox("Cell X-ray", options.wrcCellsXRay)) p["wrcCellsXRay"] = options.wrcCellsXRay;
            const Gui::DropdownList filters = {{0, "All"}, {1, "1x"}, {2, "2x"}, {4, "4x"},
                {8, "8x"}, {16, "16x"}, {32, "32x"}, {64, "64x"}};
            if (widgets.dropdown("Cell LOD", filters, options.wrcCellsLod)) p["wrcCellsLod"] = options.wrcCellsLod;
            if (widgets.var("Cell opacity", options.wrcCellsOpacity, 0.f, 1.f, 0.05f)) p["wrcCellsOpacity"] = options.wrcCellsOpacity;
            const float width = options.wrcCellScale * std::min(mSpacing.x, std::min(mSpacing.y, mSpacing.z));
            widgets.text("Base cell width: " + std::to_string(width) + " world units");
            if (options.wrcCellsLod) widgets.text("Selected width: " + std::to_string(width * options.wrcCellsLod));
            widgets.text("LOD: 1x cyan, 2x green, 4x yellow, 8x orange");
            widgets.text("16x pink, 32x purple, 64x blue");
            widgets.text("Occupied cells from the last probe update. Overlay affects display only.");
            if (options.wrcBypassSharing) widgets.text("Bypass creates no occupied WRC cells.");
        }
    }
    if (mHasDirectLighting)
    {
        if (widgets.checkbox("Use RTXDI direct light", options.useRTXDI)) p["useRTXDI"] = options.useRTXDI;
        widgets.tooltip("Use ReSTIR DI for camera-visible lighting. Disable to compare the original one-sample lighting; probe history is preserved.");
    }
    if (widgets.checkbox("Show probes", options.showProbes)) p["showProbes"] = options.showProbes;
    if (widgets.checkbox("Probe relocation", options.relocation)) p["enableRelocation"] = options.relocation;
    if (widgets.checkbox("Probe classification", options.classification)) p["enableClassification"] = options.classification;
    if (widgets.var("Grid counts", options.counts, 2u, 32u)) p["gridCounts"] = options.counts;
    if (widgets.var("Rays per probe", options.rays, 64u, 512u)) p["raysPerProbe"] = options.rays;
    if (widgets.var("History weight", options.hysteresis, 0.f, 0.999f, 0.005f)) p["hysteresis"] = options.hysteresis;
    if (widgets.var("Normal bias", options.normalBias, 0.f, 1.f, 0.005f)) p["normalBias"] = options.normalBias;
    if (widgets.var("View bias", options.viewBias, 0.f, 1.f, 0.005f)) p["viewBias"] = options.viewBias;
    if (widgets.var("Relocation min distance", options.minFrontfaceDistance, 0.f, 1.f, 0.005f))
        p["minFrontfaceDistance"] = options.minFrontfaceDistance;
    widgets.tooltip("Normal bias, view bias and relocation minimum distance are fractions of the smallest probe spacing.");
    if (widgets.var("GI intensity", options.intensity, 0.f, 10.f, 0.05f)) p["intensity"] = options.intensity;
    if (widgets.checkbox("Fit bounds to scene", options.autoBounds)) p["autoBounds"] = options.autoBounds;
    widgets.tooltip("Enclose the scene bounds with 5% padding on each side, keeping surfaces out of the volume's exterior fade.");
    if (!options.autoBounds)
    {
        bool changed = widgets.var("Grid min", options.gridMin, -1e6f, 1e6f, 0.1f);
        changed |= widgets.var("Grid max", options.gridMax, -1e6f, 1e6f, 0.1f);
        if (changed && all(options.gridMax > options.gridMin))
        {
            p["gridMin"] = options.gridMin;
            p["gridMax"] = options.gridMax;
        }
        else if (changed) widgets.text("Grid max must exceed grid min.");
    }
    if (!p.empty()) setProperties(p);
}
