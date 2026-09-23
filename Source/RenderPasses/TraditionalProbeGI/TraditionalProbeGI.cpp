/***************************************************************************
 # Copyright (c) 2015-24, NVIDIA CORPORATION. All rights reserved.
 #
 # Redistribution and use in source and binary forms, with or without
 # modification, are permitted provided that the following conditions
 # are met:
 #  * Redistributions of source code must retain the above copyright
 #    notice, this list of conditions and the following disclaimer.
 #  * Redistributions in binary form must reproduce the above copyright
 #    notice, this list of conditions and the following disclaimer in the
 #    documentation and/or other materials provided with the distribution.
 #  * Neither the name of NVIDIA CORPORATION nor the names of its
 #    contributors may be used to endorse or promote products derived
 #    from this software without specific prior written permission.
 #
 # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS "AS IS" AND ANY
 # EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 # IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 # PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 # CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 # EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 # PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 # PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 # OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 # (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 # OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 **************************************************************************/
#include "TraditionalProbeGI.h"
#include "RenderGraph/RenderPassHelpers.h"
#include "RenderGraph/RenderPassStandardFlags.h"
#include <fstream>
#include <iomanip>
#include <limits>
#include <cmath>

extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry)
{
    registry.registerClass<RenderPass, TraditionalProbeGI>();
}

namespace
{
const char kShaderFile[] = "RenderPasses/TraditionalProbeGI/TraditionalProbeGI.rt.slang";
const uint32_t kMaxPayloadSizeBytes = 72u;
const uint32_t kMaxRecursionDepth = 2u;
const ChannelList kInputChannels = {
    {"vbuffer", "gVBuffer", "Packed camera hit"},
    {"viewW", "gViewW", "World-space view direction", true},
};
const ChannelList kOutputChannels = {
    {"color", "gOutputColor", "Probe diffuse plus analytic direct and emission", false, ResourceFormat::RGBA32Float},
    {"probeLighting", "gProbeLighting", "Diffuse probe contribution", false, ResourceFormat::RGBA32Float},
};
bool finite3(float3 v)
{
    return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
}
} // namespace

TraditionalProbeGI::TraditionalProbeGI(ref<Device> device, const Properties& props) : RenderPass(device)
{
    bool hasMin = false, hasMax = false;
    for (const auto& [key, value] : props)
    {
        if (key == "gridCounts")
            mCounts = value;
        else if (key == "gridMin")
        {
            mGridMin = value;
            hasMin = true;
        }
        else if (key == "gridMax")
        {
            mGridMax = value;
            hasMax = true;
        }
        else if (key == "samplesPerProbe")
            mSamples = value;
        else if (key == "samplesPerFrame")
            mBatch = value;
        else if (key == "maxBounces")
            mMaxBounces = value;
        else if (key == "mode")
            mMode = value.operator std::string();
        else if (key == "cacheFile")
            mCacheFile = value.operator std::filesystem::path();
        else if (key == "sceneRevision")
            mRevision = value.operator std::string();
        else if (key == "intensity")
            mIntensity = value;
        else if (key == "normalBias")
            mNormalBias = value;
        else if (key == "enableProbes")
            mEnable = value;
        else if (key == "showProbeOnly")
            mProbeOnly = value;
        else
            FALCOR_THROW("TraditionalProbeGI: unknown property '{}'", key);
    }
    FALCOR_CHECK(hasMin == hasMax, "Specify both gridMin and gridMax.");
    mExplicitBounds = hasMin;
    FALCOR_CHECK(all(mCounts >= uint3(2)) && all(mCounts <= uint3(32)), "gridCounts must be 2..32 per axis.");
    FALCOR_CHECK(
        mSamples >= 1 && mSamples <= 65536 && mBatch >= 1 && mBatch <= 64 && mMaxBounces <= 8, "Invalid probe sampling parameters."
    );
    FALCOR_CHECK(
        std::isfinite(mIntensity) && mIntensity >= 0 && std::isfinite(mNormalBias) && mNormalBias >= 0, "Invalid probe intensity/bias."
    );
    FALCOR_CHECK(mMode == "bake" || mMode == "load" || mMode == "auto", "mode must be bake/load/auto.");
    FALCOR_CHECK(!mCacheFile.empty(), "cacheFile is required.");
    mpSampleGenerator = SampleGenerator::create(mpDevice, SAMPLE_GENERATOR_UNIFORM);
}

Properties TraditionalProbeGI::getProperties() const
{
    Properties p;
    p["gridCounts"] = mCounts;
    if (mExplicitBounds)
    {
        p["gridMin"] = mGridMin;
        p["gridMax"] = mGridMax;
    }
    p["samplesPerProbe"] = mSamples;
    p["samplesPerFrame"] = mBatch;
    p["maxBounces"] = mMaxBounces;
    p["mode"] = mMode;
    p["cacheFile"] = mCacheFile;
    p["sceneRevision"] = mRevision;
    p["intensity"] = mIntensity;
    p["normalBias"] = mNormalBias;
    p["enableProbes"] = mEnable;
    p["showProbeOnly"] = mProbeOnly;
    return p;
}

RenderPassReflection TraditionalProbeGI::reflect(const CompileData&)
{
    RenderPassReflection r;
    addRenderPassInputs(r, kInputChannels);
    addRenderPassOutputs(r, kOutputChannels);
    return r;
}

void TraditionalProbeGI::resetBake()
{
    std::vector<float4> zero(probeCount() * 9, float4(0));
    mpSH = mpDevice->createStructuredBuffer(
        sizeof(float4),
        uint32_t(zero.size()),
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess,
        MemoryType::DeviceLocal,
        zero.data()
    );
    mCompleted = 0;
    mReady = false;
    mDirty = true;
    logInfo("TraditionalProbeGI: BAKE start, {} probes x {} samples, cache {}", probeCount(), mSamples, mCacheFile.string());
}

void TraditionalProbeGI::initializeProbes()
{
    if (!mExplicitBounds)
    {
        const auto& bounds = mpScene->getSceneBounds();
        auto inset = bounds.extent() * 0.05f;
        mGridMin = bounds.minPoint + inset;
        mGridMax = bounds.maxPoint - inset;
    }
    FALCOR_CHECK(finite3(mGridMin) && finite3(mGridMax) && all(mGridMax > mGridMin), "Invalid probe volume bounds.");
    auto path = std::filesystem::weakly_canonical(mpScene->getPath());
    mSceneKey = path.generic_string();
    mSceneStamp = std::filesystem::exists(path) ? int64_t(std::filesystem::last_write_time(path).time_since_epoch().count()) : 0;
    bool loaded = false;
    if (mMode != "bake")
        loaded = loadCache();
    if (!loaded)
    {
        FALCOR_CHECK(mMode != "load", "TraditionalProbeGI: cache missing, invalid or incompatible: {}", mCacheFile.string());
        resetBake();
    }
    mInitialized = true;
}

bool TraditionalProbeGI::loadCache()
{
    auto reject = [&](const char* why)
    {
        logWarning("TraditionalProbeGI: cache rejected: {} ({})", why, mCacheFile.string());
        return false;
    };
    std::ifstream in(mCacheFile);
    if (!in)
        return reject("cannot open");
    std::string magic, scene, revision;
    uint32_t version = 0, samples = 0, bounces = 0;
    int64_t stamp = 0;
    uint3 counts = {};
    float3 lo = {}, hi = {};
    in >> magic >> version >> std::quoted(scene) >> stamp >> std::quoted(revision);
    in >> counts.x >> counts.y >> counts.z >> samples >> bounces;
    in >> lo.x >> lo.y >> lo.z >> hi.x >> hi.y >> hi.z;
    if (!in || magic != "FALCOR_PROBE_SH" || version != 1)
        return reject("bad header/version");
    if (scene != mSceneKey || stamp != mSceneStamp || revision != mRevision || any(counts != mCounts) || samples != mSamples ||
        bounces != mMaxBounces || !finite3(lo) || !finite3(hi) || any(abs(lo - mGridMin) > float3(1e-5f)) ||
        any(abs(hi - mGridMax) > float3(1e-5f)))
        return reject("metadata mismatch");
    std::vector<float4> data(probeCount() * 9);
    for (auto& c : data)
    {
        in >> c.x >> c.y >> c.z;
        c.w = 0;
        if (!in || !finite3(float3(c.x, c.y, c.z)))
            return reject("truncated/non-finite coefficients");
        c *= float(mSamples); // Same GPU representation as completed baking: unnormalized sums.
        if (!finite3(float3(c.x, c.y, c.z)))
            return reject("coefficient overflow");
    }
    std::string extra;
    if (in >> extra)
        return reject("trailing data");
    mpSH = mpDevice->createStructuredBuffer(
        sizeof(float4),
        uint32_t(data.size()),
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess,
        MemoryType::DeviceLocal,
        data.data()
    );
    mCompleted = mSamples;
    mReady = true;
    mDirty = true;
    logInfo("TraditionalProbeGI: LOAD ready, {} probes, no baking dispatch", probeCount());
    return true;
}

void TraditionalProbeGI::saveCache()
{
    std::vector<float4> data(probeCount() * 9);
    mpSH->getBlob(data.data(), 0, data.size() * sizeof(float4));
    if (!mCacheFile.parent_path().empty())
        std::filesystem::create_directories(mCacheFile.parent_path());
    std::ofstream out(mCacheFile, std::ios::trunc);
    FALCOR_CHECK(bool(out), "Cannot write probe cache {}", mCacheFile.string());
    out << std::setprecision(std::numeric_limits<float>::max_digits10);
    out << "FALCOR_PROBE_SH 1\n" << std::quoted(mSceneKey) << '\n' << mSceneStamp << '\n' << std::quoted(mRevision) << '\n';
    out << mCounts.x << ' ' << mCounts.y << ' ' << mCounts.z << ' ' << mSamples << ' ' << mMaxBounces << '\n';
    out << mGridMin.x << ' ' << mGridMin.y << ' ' << mGridMin.z << ' ' << mGridMax.x << ' ' << mGridMax.y << ' ' << mGridMax.z << '\n';
    for (auto c : data)
    {
        c /= float(mSamples);
        FALCOR_CHECK(finite3(float3(c.x, c.y, c.z)), "Non-finite probe coefficient; bake failed.");
        out << c.x << ' ' << c.y << ' ' << c.z << '\n';
    }
    out.flush();
    FALCOR_CHECK(bool(out), "Failed writing probe cache {}", mCacheFile.string());
    logInfo("TraditionalProbeGI: BAKE complete and SAVED {}", mCacheFile.string());
}

void TraditionalProbeGI::execute(RenderContext* ctx, const RenderData& data)
{
    if (!mpScene)
    {
        for (const auto& c : kOutputChannels)
            if (auto t = data.getTexture(c.name))
                ctx->clearTexture(t.get());
        return;
    }
    // First-frame scene initialization is not a user edit. Camera flags are intentionally omitted.
    using U = IScene::UpdateFlags;
    const auto invalidating = U::GeometryMoved | U::GeometryChanged | U::MeshesChanged | U::MaterialsChanged | U::LightsMoved |
                              U::LightIntensityChanged | U::LightPropertiesChanged | U::LightCountChanged | U::EnvMapChanged |
                              U::EnvMapPropertiesChanged | U::RenderSettingsChanged | U::EmissiveMaterialsChanged | U::CurvesMoved |
                              U::DisplacementChanged | U::SDFGeometryChanged | U::RecompileNeeded;
    if (mFrame > 0 && is_set(mpScene->getUpdates(), invalidating))
        FALCOR_THROW("TraditionalProbeGI: scene lighting/geometry changed. Restart with mode=bake and a new sceneRevision.");
    if (!mInitialized)
        initializeProbes();
    if (mRebake)
    {
        resetBake();
        mRebake = false;
    }
    if (mpScene->getRenderSettings().useEmissiveLights)
        mpScene->getLightCollection(ctx);
    auto p = mTracer.pProgram;
    p->addDefine("MAX_BOUNCES", std::to_string(mMaxBounces));
    p->addDefine("COMPUTE_DIRECT", "1");
    p->addDefine("USE_IMPORTANCE_SAMPLING", "1");
    p->addDefine("USE_ANALYTIC_LIGHTS", mpScene->useAnalyticLights() ? "1" : "0");
    p->addDefine("USE_EMISSIVE_LIGHTS", mpScene->useEmissiveLights() ? "1" : "0");
    p->addDefine("USE_ENV_LIGHT", mpScene->useEnvLight() ? "1" : "0");
    p->addDefine("USE_ENV_BACKGROUND", mpScene->useEnvBackground() ? "1" : "0");
    p->addDefines(getValidResourceDefines(kInputChannels, data));
    p->addDefines(getValidResourceDefines(kOutputChannels, data));
    if (!mTracer.pVars)
        prepareVars();
    auto var = mTracer.pVars->getRootVar();
    for (const auto& c : kInputChannels)
        var[c.texname] = data.getTexture(c.name);
    for (const auto& c : kOutputChannels)
        var[c.texname] = data.getTexture(c.name);
    var["gProbeSH"] = mpSH;
    auto cb = var["ProbeCB"];
    cb["gGridCounts"] = mCounts;
    cb["gGridMin"] = mGridMin;
    cb["gGridMax"] = mGridMax;
    cb["gSampleTotal"] = mSamples;
    cb["gIntensity"] = mIntensity;
    cb["gNormalBias"] = mNormalBias;
    cb["gProbeOnly"] = mProbeOnly;
    var["CB"]["gFrameCount"] = mFrame;
    var["CB"]["gPRNGDimension"] = 0u;
    if (!mReady)
    {
        uint32_t batch = std::min(mBatch, mSamples - mCompleted);
        cb["gBake"] = true;
        cb["gSampleStart"] = mCompleted;
        cb["gSampleBatch"] = batch;
        mpScene->raytrace(ctx, p.get(), mTracer.pVars, uint3(probeCount(), 1, 1));
        ctx->uavBarrier(mpSH.get());
        mCompleted += batch;
        if (mCompleted == mSamples)
        {
            saveCache();
            mReady = true;
            mDirty = true;
        }
    }
    cb["gBake"] = false;
    cb["gReady"] = mReady && mEnable;
    mpScene->raytrace(ctx, p.get(), mTracer.pVars, uint3(data.getDefaultTextureDims(), 1));
    if (mDirty)
    {
        auto& dict = data.getDictionary();
        auto flags = dict.getValue(kRenderPassRefreshFlags, RenderPassRefreshFlags::None);
        dict[kRenderPassRefreshFlags] = flags | RenderPassRefreshFlags::RenderOptionsChanged;
        mDirty = false;
    }
    ++mFrame;
}

void TraditionalProbeGI::renderUI(Gui::Widgets& w)
{
    w.text(mReady ? "Baked probes ready (sampling only)" : "Baking probes...");
    w.text(std::to_string(mCompleted) + " / " + std::to_string(mSamples) + " samples per probe");
    mDirty |= w.checkbox("Enable probes", mEnable);
    mDirty |= w.checkbox("Probe lighting only", mProbeOnly);
    mDirty |= w.var("Probe intensity", mIntensity, 0.f, 10.f);
    if (w.button("Re-bake and save"))
        mRebake = true;
    w.text("Static diffuse SH. No visibility correction; thin-wall light leaks are expected.");
}

void TraditionalProbeGI::setScene(RenderContext* pRenderContext, const ref<Scene>& pScene)
{
    mInitialized = false;
    mReady = false;
    mpSH = nullptr;
    mRebake = false;
    // Clear data for previous scene.
    // After changing scene, the raytracing program should to be recreated.
    mTracer.pProgram = nullptr;
    mTracer.pBindingTable = nullptr;
    mTracer.pVars = nullptr;
    mFrame = 0;

    // Set new scene.
    mpScene = pScene;

    if (mpScene)
    {
        if (pScene->hasGeometryType(Scene::GeometryType::Custom))
        {
            logWarning("TraditionalProbeGI: This render pass does not support custom primitives.");
        }

        // Create ray tracing program.
        ProgramDesc desc;
        desc.addShaderModules(mpScene->getShaderModules());
        desc.addShaderLibrary(kShaderFile);
        desc.setMaxPayloadSize(kMaxPayloadSizeBytes);
        desc.setMaxAttributeSize(mpScene->getRaytracingMaxAttributeSize());
        desc.setMaxTraceRecursionDepth(kMaxRecursionDepth);

        mTracer.pBindingTable = RtBindingTable::create(2, 2, mpScene->getGeometryCount());
        auto& sbt = mTracer.pBindingTable;
        sbt->setRayGen(desc.addRayGen("rayGen"));
        sbt->setMiss(0, desc.addMiss("scatterMiss"));
        sbt->setMiss(1, desc.addMiss("shadowMiss"));

        if (mpScene->hasGeometryType(Scene::GeometryType::TriangleMesh))
        {
            sbt->setHitGroup(
                0,
                mpScene->getGeometryIDs(Scene::GeometryType::TriangleMesh),
                desc.addHitGroup("scatterTriangleMeshClosestHit", "scatterTriangleMeshAnyHit")
            );
            sbt->setHitGroup(
                1, mpScene->getGeometryIDs(Scene::GeometryType::TriangleMesh), desc.addHitGroup("", "shadowTriangleMeshAnyHit")
            );
        }

        if (mpScene->hasGeometryType(Scene::GeometryType::DisplacedTriangleMesh))
        {
            sbt->setHitGroup(
                0,
                mpScene->getGeometryIDs(Scene::GeometryType::DisplacedTriangleMesh),
                desc.addHitGroup("scatterDisplacedTriangleMeshClosestHit", "", "displacedTriangleMeshIntersection")
            );
            sbt->setHitGroup(
                1,
                mpScene->getGeometryIDs(Scene::GeometryType::DisplacedTriangleMesh),
                desc.addHitGroup("", "", "displacedTriangleMeshIntersection")
            );
        }

        if (mpScene->hasGeometryType(Scene::GeometryType::Curve))
        {
            sbt->setHitGroup(
                0, mpScene->getGeometryIDs(Scene::GeometryType::Curve), desc.addHitGroup("scatterCurveClosestHit", "", "curveIntersection")
            );
            sbt->setHitGroup(1, mpScene->getGeometryIDs(Scene::GeometryType::Curve), desc.addHitGroup("", "", "curveIntersection"));
        }

        if (mpScene->hasGeometryType(Scene::GeometryType::SDFGrid))
        {
            sbt->setHitGroup(
                0,
                mpScene->getGeometryIDs(Scene::GeometryType::SDFGrid),
                desc.addHitGroup("scatterSdfGridClosestHit", "", "sdfGridIntersection")
            );
            sbt->setHitGroup(1, mpScene->getGeometryIDs(Scene::GeometryType::SDFGrid), desc.addHitGroup("", "", "sdfGridIntersection"));
        }

        mTracer.pProgram = Program::create(mpDevice, desc, mpScene->getSceneDefines());
    }
}

void TraditionalProbeGI::prepareVars()
{
    FALCOR_ASSERT(mpScene);
    FALCOR_ASSERT(mTracer.pProgram);

    // Configure program.
    mTracer.pProgram->addDefines(mpSampleGenerator->getDefines());
    mTracer.pProgram->setTypeConformances(mpScene->getTypeConformances());

    // Create program variables for the current program.
    // This may trigger shader compilation. If it fails, throw an exception to abort rendering.
    mTracer.pVars = RtProgramVars::create(mpDevice, mTracer.pProgram, mTracer.pBindingTable);

    // Bind utility classes into shared data.
    auto var = mTracer.pVars->getRootVar();
    mpSampleGenerator->bindShaderData(var);
}
