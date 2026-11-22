#include "RTXGIDDGI.h"

namespace
{
constexpr uint32_t kEntries = 1u << 20;
const auto kFlags = ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess;
}

void RTXGIDDGI::prepareWorldCache(RenderContext* context)
{
    if (mReallocate || !mpWCState)
    {
        // The shared host supplies material/light bindings and FG only. This
        // backend owns no DDGI volume and dispatches no SDK probe work.
        mpVolume = nullptr; mpRayData = nullptr;
        mpIrradiance = mpDistance = mpProbeData = mpVariability = nullptr;
        if (!mpWCState)
        {
            mpWCState = mpDevice->createStructuredBuffer(4, kEntries, kFlags);
            mpWCKeys = mpDevice->createStructuredBuffer(16, kEntries, kFlags);
            mpWCLighting = mpDevice->createStructuredBuffer(16, kEntries, kFlags);
            mpWCAccumulation = mpDevice->createStructuredBuffer(16, kEntries, kFlags);
            mpWCAge = mpDevice->createStructuredBuffer(4, kEntries, kFlags);
            mpWCStats = mpDevice->createStructuredBuffer(4, 4, kFlags);
        }
        if (!mpDiagnostics) mpDiagnostics = mpDevice->createStructuredBuffer(4, 4, kFlags);
        mReallocate = false;
        mWorldCacheReset = true;
    }
    if (!mWorldCacheTrace.program)
        buildRayProgram(mWorldCacheTrace, "RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang", "updateWorldCache");
    if (!mpWorldCacheResolve)
        mpWorldCacheResolve = ComputePass::create(mpDevice, "RenderPasses/RTXGIDDGI/LumenWorldCache.cs.slang", "resolve");
    if (mWorldCacheReset || mResetPending)
    {
        for (auto buffer : {mpWCState, mpWCKeys, mpWCLighting, mpWCAccumulation, mpWCAge, mpWCStats, mpDiagnostics})
            context->clearUAV(buffer->getUAV().get(), uint4(0));
        mUpdatedFrames = mWorldCacheFrames = 0;
        mWorldCacheReset = mResetPending = false;
    }
}

void RTXGIDDGI::bindWorldCache(const ShaderVar& root)
{
    root["gWCState"] = mpWCState;
    root["gWCKeys"] = mpWCKeys;
    root["gWCLighting"] = mpWCLighting;
    root["gWCAccumulation"] = mpWCAccumulation;
    root["gWCAge"] = mpWCAge;
    root["gWCStats"] = mpWCStats;
    auto cb = root["WorldCacheCB"];
    cb["gWCSize"] = kEntries;
    cb["gWCDensity"] = mOptions.worldCacheDensity;
    cb["gWCDownsample"] = mOptions.worldCacheDownsample;
    cb["gWCBounces"] = mOptions.worldCacheBounces;
    cb["gWCHistory"] = mOptions.worldCacheHistory;
    cb["gWCMaxAge"] = 64u;
    cb["gWCMinCell"] = 0.025f;
    cb["gWCMaxIntensity"] = mOptions.worldCacheMaxIntensity;
    cb["gWCCamera"] = mpScene->getCamera()->getPosition();
}

void RTXGIDDGI::updateWorldCache(RenderContext* context, const RenderData& data)
{
    FALCOR_PROFILE(context, "WorldCacheUpdate");
    context->clearUAV(mpWCStats->getUAV().get(), uint4(0));
    {
        FALCOR_PROFILE(context, "CachePaths");
        bindRayProgram(mWorldCacheTrace, data);
        uint2 dim = (data.getDefaultTextureDims() + uint2(mOptions.worldCacheDownsample - 1u)) / mOptions.worldCacheDownsample;
        mpScene->raytrace(context, mWorldCacheTrace.program.get(), mWorldCacheTrace.vars, uint3(dim, 1));
    }
    for (auto buffer : {mpWCAccumulation, mpWCState, mpWCKeys, mpWCStats}) context->uavBarrier(buffer.get());
    {
        FALCOR_PROFILE(context, "CacheResolve");
        bindWorldCache(mpWorldCacheResolve->getRootVar());
        mpWorldCacheResolve->execute(context, uint3(kEntries, 1, 1));
    }
    for (auto buffer : {mpWCLighting, mpWCAccumulation, mpWCState, mpWCAge, mpWCStats}) context->uavBarrier(buffer.get());
    ++mWorldCacheFrames;
}

void RTXGIDDGI::renderWorldCacheUI(Gui::Widgets& widgets)
{
    widgets.text(mOptions.sharc ? "SHaRC | NVIDIA SDK 1.8.3" : "WorldCache | experimental Falcor adaptation");
    widgets.text("Independent diffuse surface cache; no DDGI probes.");
    widgets.text("Cache updates: " + std::to_string(mWorldCacheFrames));
    auto o = mOptions;
    Properties p;
    if (widgets.checkbox("Update cache", o.update)) p["updateEnabled"] = o.update;
    if (widgets.button("Reset cache")) reset();
    if (o.sharc)
    {
        if (widgets.var("Cell density", o.sharcSceneScale, 1.f, 63.f)) p["sharcSceneScale"] = o.sharcSceneScale;
        widgets.text("Official defaults: downscale 5, max vertices 8, history 20.");
        widgets.text("4M entries, stale age 60, material demodulation on.");
    }
    else
    {
        if (widgets.var("Cell density", o.worldCacheDensity, 1.f, 63.f)) p["worldCacheDensity"] = o.worldCacheDensity;
        if (widgets.var("Path downsample", o.worldCacheDownsample, 1u, 32u)) p["worldCacheDownsample"] = o.worldCacheDownsample;
        if (widgets.var("Cache path bounces", o.worldCacheBounces, 1u, 8u)) p["worldCacheBounces"] = o.worldCacheBounces;
        if (widgets.var("Cache history", o.worldCacheHistory, 1u, 255u)) p["worldCacheHistory"] = o.worldCacheHistory;
        if (widgets.var("Radiance clamp (0 = off)", o.worldCacheMaxIntensity, 0.f, 10000.f)) p["worldCacheMaxIntensity"] = o.worldCacheMaxIntensity;
    }
    if (auto gather = widgets.group("Final gather", true))
    {
        uint32_t resolution = o.halfResolutionGather ? 0u : 1u;
        if (gather.dropdown("Resolution", {{0, "Half"}, {1, "Full"}}, resolution)) p["halfResolutionGather"] = resolution == 0;
        if (gather.checkbox("Jitter sample position", o.jitterHalfGather)) p["jitterHalfGather"] = o.jitterHalfGather;
        gather.text("Same FG and reconstruction as DDGI. ReSTIR disabled.");
        gather.text("Accumulate > Enabled controls screen accumulation.");
    }
    if (!p.empty()) setProperties(p);
}
