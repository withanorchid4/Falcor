#include "RTXGIDDGI.h"
#include <random>

// NVIDIA RTXGI Pathtracer 04372d7f defaults. Only spatial scale/level bias
// are adjusted to match the WorldCache cell sizes used by this experiment.
namespace { constexpr uint32_t kSharcEntries = 1u << 22; }

void RTXGIDDGI::prepareSharc(RenderContext* context)
{
    if (mReallocate || !mpSharcHash)
    {
        mpVolume = nullptr; mpRayData = nullptr;
        mpIrradiance = mpDistance = mpProbeData = mpVariability = nullptr;
        if (!mpSharcHash)
        {
            auto flags = ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess;
            mpSharcHash = mpDevice->createStructuredBuffer(8, kSharcEntries, flags);
            mpSharcAccum = mpDevice->createStructuredBuffer(16, kSharcEntries, flags);
            mpSharcResolved = mpDevice->createStructuredBuffer(16, kSharcEntries, flags);
            mpSharcStats = mpDevice->createStructuredBuffer(4, 4, flags);
        }
        if (!mpDiagnostics) mpDiagnostics = mpDevice->createStructuredBuffer(4, 4, ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess);
        mReallocate = false; mWorldCacheReset = true;
    }
    if (!mWorldCacheTrace.program) buildRayProgram(mWorldCacheTrace, "RenderPasses/RTXGIDDGI/RTXGIDDGI.rt.slang", "updateSharcCache");
    if (!mpWorldCacheResolve)
    {
        ProgramDesc desc;
        desc.addShaderLibrary("RenderPasses/RTXGIDDGI/SharcCache.cs.slang").csEntry("resolve");
        desc.setShaderModel(ShaderModel::SM6_6);
        mpWorldCacheResolve = ComputePass::create(mpDevice, desc);
    }
    if (mWorldCacheReset || mResetPending)
    {
        for (auto b : {mpSharcHash, mpSharcAccum, mpSharcResolved, mpSharcStats, mpDiagnostics}) context->clearUAV(b->getUAV().get(), uint4(0));
        mUpdatedFrames = mWorldCacheFrames = 0;
        mSharcPreviousCamera = mpScene->getCamera()->getPosition();
        mWorldCacheReset = mResetPending = false;
    }
}
void RTXGIDDGI::bindSharc(const ShaderVar& root)
{
    root["gSharcHash"] = mpSharcHash; root["gSharcAccum"] = mpSharcAccum;
    root["gSharcResolved"] = mpSharcResolved;
    root["gSharcStats"] = mpSharcStats;
    auto cb = root["SharcCB"];
    cb["gSharcSize"] = kSharcEntries;
    cb["gSharcScale"] = mOptions.sharcSceneScale;
    cb["gSharcDownsample"] = 5u;
    cb["gSharcBounces"] = 8u;
    cb["gSharcHistory"] = 20u;
    std::mt19937 rng(mWorldCacheFrames);
    std::uniform_real_distribution<float> offset(-.5f, .5f);
    const float jitterX = offset(rng), jitterY = offset(rng);
    cb["gSharcPixelOffset"] = float2(jitterX, jitterY);
    cb["gSharcFrame"] = mWorldCacheFrames;
    cb["gSharcCamera"] = mpScene->getCamera()->getPosition();
    cb["gSharcPreviousCamera"] = mSharcPreviousCamera;
}
void RTXGIDDGI::updateSharc(RenderContext* context, const RenderData& data)
{
    FALCOR_PROFILE(context, "SHaRCUpdate");
    context->clearUAV(mpSharcStats->getUAV().get(), uint4(0));
    {
        FALCOR_PROFILE(context, "CachePaths");
        bindRayProgram(mWorldCacheTrace, data);
        uint2 dim = max(data.getDefaultTextureDims() / 5u, uint2(1u));
        mpScene->raytrace(context, mWorldCacheTrace.program.get(), mWorldCacheTrace.vars, uint3(dim, 1));
    }
    for (auto b : {mpSharcHash, mpSharcAccum, mpSharcResolved, mpSharcStats}) context->uavBarrier(b.get());
    {
        FALCOR_PROFILE(context, "CacheResolve");
        bindSharc(mpWorldCacheResolve->getRootVar());
        mpWorldCacheResolve->execute(context, uint3(kSharcEntries,1,1));
    }
    for (auto b : {mpSharcHash, mpSharcAccum, mpSharcResolved, mpSharcStats}) context->uavBarrier(b.get());
    mSharcPreviousCamera = mpScene->getCamera()->getPosition();
    ++mWorldCacheFrames;
}
