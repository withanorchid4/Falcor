#include "RTXGIDDGI.h"
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
const ChannelList kInputs = {
    {"vbuffer", "gVBuffer", "Camera surface visibility"},
    {"viewW", "gViewW", "Camera view direction", true},
};
const ChannelList kOutputs = {
    {"color", "gOutputColor", "Direct light, emission, and dynamic DDGI", false, ResourceFormat::RGBA32Float},
    {"indirect", "gOutputIndirect", "DDGI diffuse contribution before display mapping", true, ResourceFormat::RGBA32Float},
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
    p["gridCounts"] = mOptions.counts;
    p["raysPerProbe"] = mOptions.rays;
    p["hysteresis"] = mOptions.hysteresis;
    p["normalBias"] = mOptions.normalBias;
    p["viewBias"] = mOptions.viewBias;
    p["intensity"] = mOptions.intensity;
    p["gridMin"] = mOptions.gridMin;
    p["gridMax"] = mOptions.gridMax;
    p["autoBounds"] = mOptions.autoBounds;
    p["enableRelocation"] = mOptions.relocation;
    p["enableClassification"] = mOptions.classification;
    p["updateEnabled"] = mOptions.update;
    p["enableGI"] = mOptions.enableGI;
    p["showProbes"] = mOptions.showProbes;
    p["indirectOnly"] = mOptions.indirectOnly;
    return p;
}

void RTXGIDDGI::setProperties(const Properties& properties)
{
    Options next = mOptions;
    for (const auto& [name, value] : properties)
    {
        if (name == "gridCounts") next.counts = value;
        else if (name == "raysPerProbe") next.rays = value;
        else if (name == "hysteresis") next.hysteresis = value;
        else if (name == "normalBias") next.normalBias = value;
        else if (name == "viewBias") next.viewBias = value;
        else if (name == "intensity") next.intensity = value;
        else if (name == "gridMin") next.gridMin = value;
        else if (name == "gridMax") next.gridMax = value;
        else if (name == "autoBounds") next.autoBounds = value;
        else if (name == "enableRelocation") next.relocation = value;
        else if (name == "enableClassification") next.classification = value;
        else if (name == "updateEnabled") next.update = value;
        else if (name == "enableGI") next.enableGI = value;
        else if (name == "showProbes") next.showProbes = value;
        else if (name == "indirectOnly") next.indirectOnly = value;
        else FALCOR_THROW("Unknown RTXGIDDGI property '{}'.", name);
    }
    FALCOR_CHECK(all(next.counts >= uint3(2)) && all(next.counts <= uint3(32)), "DDGI gridCounts must be 2..32 per axis.");
    FALCOR_CHECK(next.rays >= 64 && next.rays <= 512, "DDGI raysPerProbe must be 64..512 (32 rays are reserved for probe placement).");
    FALCOR_CHECK(std::isfinite(next.hysteresis) && next.hysteresis >= 0.f && next.hysteresis < 1.f, "DDGI hysteresis must be in [0,1).");
    FALCOR_CHECK(std::isfinite(next.normalBias) && next.normalBias >= 0.f && next.normalBias <= 1.f, "DDGI normalBias must be in [0,1].");
    FALCOR_CHECK(std::isfinite(next.viewBias) && next.viewBias >= 0.f && next.viewBias <= 1.f, "DDGI viewBias must be in [0,1].");
    FALCOR_CHECK(std::isfinite(next.intensity) && next.intensity >= 0.f, "DDGI intensity must be finite and nonnegative.");
    FALCOR_CHECK(all(isfinite(next.gridMin)) && all(isfinite(next.gridMax)) && all(next.gridMax > next.gridMin), "DDGI gridMax must exceed gridMin.");
    if (any(next.counts != mOptions.counts) || next.rays != mOptions.rays || next.autoBounds != mOptions.autoBounds ||
        any(next.gridMin != mOptions.gridMin) || any(next.gridMax != mOptions.gridMax)) mReallocate = true;
    if (next.relocation != mOptions.relocation || next.classification != mOptions.classification) mResetPending = true;
    mOptions = next;
    mOptionsChanged = true;
}

RenderPassReflection RTXGIDDGI::reflect(const CompileData& data)
{
    RenderPassReflection reflection;
    addRenderPassInputs(reflection, kInputs);
    addRenderPassOutputs(reflection, kOutputs);
    return reflection;
}

void RTXGIDDGI::setScene(RenderContext* context, const ref<Scene>& scene)
{
    mpScene = scene;
    mTrace = {};
    mRender = {};
    mpEnvMapSampler = nullptr;
    mpSamplerSource = nullptr;
    mReallocate = mRebuildPrograms = mResetPending = true;
    mFrame = mUpdatedFrames = 0;
    mSupported = true;
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
}

void RTXGIDDGI::createPrograms()
{
    const auto build = [&](RayProgram& ray, const char* entry)
    {
        ProgramDesc desc;
        desc.addShaderModules(mpScene->getShaderModules());
        desc.addShaderLibrary(kRayShader);
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
    };
    build(mTrace, "traceProbes");
    build(mRender, "render");
    mRebuildPrograms = false;
}

void RTXGIDDGI::allocateResources(RenderContext* context)
{
    if (mOptions.autoBounds)
    {
        const auto bounds = mpScene->getSceneBounds();
        const auto extent = max(bounds.extent(), float3(0.01f));
        const auto center = (bounds.minPoint + bounds.maxPoint) * 0.5f;
        mGridMin = center - extent * 0.45f;
        mGridMax = center + extent * 0.45f;
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
    mResetPending = false;
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
    volume.probeMinFrontfaceDistance = 0.10f * scale;
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
    bool changed = ray.program->addDefine("USE_ANALYTIC_LIGHTS", mpScene->useAnalyticLights() ? "1" : "0");
    changed |= ray.program->addDefine("USE_EMISSIVE_LIGHTS", mpScene->useEmissiveLights() ? "1" : "0");
    changed |= ray.program->addDefine("USE_ENV_LIGHT", mpScene->useEnvLight() ? "1" : "0");
    changed |= ray.program->addDefine("USE_ENV_BACKGROUND", mpScene->useEnvBackground() ? "1" : "0");
    changed |= ray.program->addDefine("OUTPUT_INDIRECT", data.getTexture("indirect") ? "1" : "0");
    changed |= ray.program->addDefine("is_valid_gViewW", data.getTexture("viewW") ? "1" : "0");
    if (changed) ray.vars = nullptr;
    if (!ray.vars)
    {
        ray.vars = RtProgramVars::create(mpDevice, ray.program, ray.table);
        mpSampleGenerator->bindShaderData(ray.vars->getRootVar());
    }
    auto root = ray.vars->getRootVar();
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
    root["gVBuffer"] = data.getTexture("vbuffer");
    root["gViewW"] = data.getTexture("viewW");
    root["gOutputColor"] = data.getTexture("color");
    if (data.getTexture("indirect")) root["gOutputIndirect"] = data.getTexture("indirect");
    auto cb = root["PerFrameCB"];
    cb["gFrameCount"] = mFrame;
    cb["gFrameDim"] = data.getDefaultTextureDims();
    cb["gEnableGI"] = mOptions.enableGI;
    cb["gIndirectOnly"] = mOptions.indirectOnly;
    cb["gShowProbes"] = mOptions.showProbes;
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
    if (!mpScene || !mSupported)
    {
        for (const auto& output : kOutputs)
            if (auto texture = data.getTexture(output.name)) context->clearTexture(texture.get());
        return;
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
    if (mReallocate) allocateResources(context);
    if (mResetPending) clearHistory(context);
    uploadConstants();
    if (mOptions.update)
    {
        bindRayProgram(mTrace, data);
        mpScene->raytrace(context, mTrace.program.get(), mTrace.vars,
                          uint3(mOptions.rays, mOptions.counts.x * mOptions.counts.z, mOptions.counts.y));
        context->uavBarrier(mpRayData.get());
        updateProbes(context);
    }
    bindRayProgram(mRender, data);
    mpScene->raytrace(context, mRender.program.get(), mRender.vars, uint3(data.getDefaultTextureDims(), 1));
    mStatus = mOptions.update ? "Updating dynamic irradiance and visibility." : "Probe updates frozen; camera and direct light remain live.";
    ++mFrame;
}

Properties RTXGIDDGI::getStats() const
{
    Properties stats;
    stats["updatedFrames"] = mUpdatedFrames;
    const bool allocated = mpProbeData && !mReallocate && mpScene && mSupported;
    stats["totalProbes"] = allocated ? mOptions.counts.x * mOptions.counts.y * mOptions.counts.z : 0u;
    stats["status"] = mStatus;
    stats["supported"] = mSupported;
    stats["gridMin"] = mGridMin;
    stats["gridMax"] = mGridMax;
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
    widgets.text("NVIDIA RTXGI-DDGI 1.3.7 | dynamic diffuse GI");
    widgets.text(mStatus);
    widgets.text("Probe updates: " + std::to_string(mUpdatedFrames));
    Properties p;
    auto options = mOptions;
    if (widgets.checkbox("Update probes", options.update)) p["updateEnabled"] = options.update;
    if (widgets.button("Reset history")) reset();
    if (widgets.checkbox("Enable DDGI", options.enableGI)) p["enableGI"] = options.enableGI;
    if (widgets.checkbox("Indirect only", options.indirectOnly)) p["indirectOnly"] = options.indirectOnly;
    if (widgets.checkbox("Show probes", options.showProbes)) p["showProbes"] = options.showProbes;
    if (widgets.checkbox("Probe relocation", options.relocation)) p["enableRelocation"] = options.relocation;
    if (widgets.checkbox("Probe classification", options.classification)) p["enableClassification"] = options.classification;
    if (widgets.var("Grid counts", options.counts, 2u, 32u)) p["gridCounts"] = options.counts;
    if (widgets.var("Rays per probe", options.rays, 64u, 512u)) p["raysPerProbe"] = options.rays;
    if (widgets.var("History weight", options.hysteresis, 0.f, 0.999f, 0.005f)) p["hysteresis"] = options.hysteresis;
    if (widgets.var("Normal bias", options.normalBias, 0.f, 1.f, 0.005f)) p["normalBias"] = options.normalBias;
    if (widgets.var("View bias", options.viewBias, 0.f, 1.f, 0.005f)) p["viewBias"] = options.viewBias;
    widgets.tooltip("Bias values are fractions of the smallest probe spacing.");
    if (widgets.var("GI intensity", options.intensity, 0.f, 10.f, 0.05f)) p["intensity"] = options.intensity;
    if (widgets.checkbox("Fit bounds to scene", options.autoBounds)) p["autoBounds"] = options.autoBounds;
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
