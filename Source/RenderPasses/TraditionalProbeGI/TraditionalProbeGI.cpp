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
#include <sstream>
#include <locale>
#include <random>
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#endif

static void registerProbeBindings(pybind11::module& m)
{
    pybind11::class_<TraditionalProbeGI, RenderPass, ref<TraditionalProbeGI>> pass(m, "TraditionalProbeGI");
    pass.def("configureBake", [](TraditionalProbeGI& self, pybind11::dict props) { self.configureBake(Properties(props)); });
    pass.def("bake", &TraditionalProbeGI::requestBake);
    pass.def("loadCache", &TraditionalProbeGI::requestLoad);
    pass.def("cancelBake", &TraditionalProbeGI::cancelBake);
    pass.def("configureDebug", [](TraditionalProbeGI& self, pybind11::dict props) { self.configureDebug(Properties(props)); });
    pass.def("pickSurface", &TraditionalProbeGI::pickSurface);
    pass.def_property_readonly("debugInfo", [](TraditionalProbeGI& self) { return self.getDebugInfo().toPython(); });
    pass.def_property_readonly("ready", &TraditionalProbeGI::isReady);
    pass.def_property_readonly("baking", &TraditionalProbeGI::isBaking);
    pass.def_property_readonly("completedSamples", &TraditionalProbeGI::getCompletedSamples);
    pass.def_property_readonly("status", &TraditionalProbeGI::getStatus);
    pass.def_property_readonly("cacheFile", &TraditionalProbeGI::getCacheFile);
    pass.def_property_readonly("settings", [](TraditionalProbeGI& self) { return self.getProperties().toPython(); });
}

extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry)
{
    registry.registerClass<RenderPass, TraditionalProbeGI>();
    ScriptBindings::registerBinding(registerProbeBindings);
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
            mConfiguredCacheFile = value.operator std::filesystem::path();
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
        else if (key == "previewUnbaked")
            mPreview = value;
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
    FALCOR_CHECK(mMode == "manual" || mMode == "bake" || mMode == "load" || mMode == "auto", "mode must be manual/bake/load/auto.");
    mpSampleGenerator = SampleGenerator::create(mpDevice, SAMPLE_GENERATOR_UNIFORM);
    mpDebugData = mpDevice->createStructuredBuffer(sizeof(float4), 28,
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, mDebugData.data());
    mpDebugDistance = mpDevice->createTexture2D(1, 1, ResourceFormat::R32Float, 1, 1, nullptr,
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess);
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
    p["cacheFile"] = mConfiguredCacheFile;
    p["sceneRevision"] = mRevision;
    p["intensity"] = mIntensity;
    p["normalBias"] = mNormalBias;
    p["enableProbes"] = mEnable;
    p["showProbeOnly"] = mProbeOnly;
    p["previewUnbaked"] = mPreview;
    return p;
}

RenderPassReflection TraditionalProbeGI::reflect(const CompileData&)
{
    RenderPassReflection r;
    addRenderPassInputs(r, kInputChannels);
    addRenderPassOutputs(r, kOutputChannels);
    r.getField("color")->bindFlags(ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess | ResourceBindFlags::RenderTarget);
    return r;
}

void TraditionalProbeGI::clearProbes()
{
    clearDebugSelection();
    std::vector<uint4> health(probeCount(), uint4(0));
    mpBakeHealth = mpDevice->createStructuredBuffer(sizeof(uint4), probeCount(),
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, health.data());
    mInvalidAttempts = mFailedSamples = 0;
    mFirstInvalidProbe = mFirstInvalidSample = 0;
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
    mBaking = false;
    mDirty = true;
}

void TraditionalProbeGI::clearDebugSelection()
{
    std::fill(mDebugData.begin(), mDebugData.end(), float4(0));
    if (mpDebugData) mpDebugData->setBlob(mDebugData.data(), 0, mDebugData.size() * sizeof(float4));
    mPickPending = mDebugRefresh = false;
    mSelectedProbe = 0;
}

void TraditionalProbeGI::pickSurface(float2 uv)
{
    FALCOR_CHECK(std::isfinite(uv.x) && std::isfinite(uv.y) && all(uv >= float2(0)) && all(uv <= float2(1)),
        "Pick coordinates must be normalized to [0,1].");
    mPickUV = uv;
    mPickPending = true;
    mDebugEnabled = true;
}

bool TraditionalProbeGI::onMouseEvent(const MouseEvent& e)
{
    if (mDebugEnabled && mPickEnabled && e.type == MouseEvent::Type::ButtonDown && e.button == Input::MouseButton::Right)
    {
        pickSurface(clamp(e.pos, float2(0), float2(1)));
        return true;
    }
    return false;
}

void TraditionalProbeGI::configureDebug(const Properties& props)
{
    // Validate the complete request before modifying live settings.
    for (const auto& [key, value] : props)
    {
        if (key == "view") FALCOR_CHECK(uint32_t(value) <= 5, "Debug view must be 0..5.");
        else if (key == "selectedProbe") FALCOR_CHECK(uint32_t(value) < probeCount(), "Probe ID out of range.");
        else if (key == "radius") FALCOR_CHECK(std::isfinite(float(value)) && float(value) >= 0.01f && float(value) <= 0.3f, "Radius out of range.");
        else if (key == "exposure") FALCOR_CHECK(std::isfinite(float(value)) && std::abs(float(value)) <= 10.f, "Exposure out of range.");
        else if (key == "normalBias") FALCOR_CHECK(std::isfinite(float(value)) && float(value) >= 0.f && float(value) <= 1.f, "Bias out of range.");
        else if (key != "enabled" && key != "pickEnabled" && key != "showProbes" && key != "showBounds" && key != "showLinks" &&
                 key != "showIds" && key != "xray" && key != "preview" && key != "radiance" && key != "negative" && key != "onlyContributors")
            FALCOR_THROW("Unknown debug setting '{}'", key);
        else (void)bool(value);
    }
    for (const auto& [key, value] : props)
    {
        if (key == "enabled") mDebugEnabled = value;
        else if (key == "pickEnabled") mPickEnabled = value;
        else if (key == "showProbes") mShowProbes = value;
        else if (key == "showBounds") mShowBounds = value;
        else if (key == "showLinks") mShowLinks = value;
        else if (key == "showIds") mShowIds = value;
        else if (key == "onlyContributors") mOnlyContributors = value;
        else if (key == "xray") mDebugXRay = value;
        else if (key == "preview") mShowProbePreview = value;
        else if (key == "radiance") mPreviewRadiance = value;
        else if (key == "negative") mShowNegative = value;
        else if (key == "view") mDebugView = value;
        else if (key == "selectedProbe") mSelectedProbe = value;
        else if (key == "radius") mProbeRadius = value;
        else if (key == "exposure") mDebugExposure = value;
        else if (key == "normalBias") mNormalBias = value;
    }
    mDebugRefresh = mDirty = true;
}

Properties TraditionalProbeGI::getDebugInfo() const
{
    auto xyz = [](float4 v) { return float3(v.x, v.y, v.z); };
    Properties p;
    p["enabled"] = mDebugEnabled;
    p["valid"] = mDebugData[0].w > 0.f;
    p["position"] = xyz(mDebugData[0]);
    p["normal"] = xyz(mDebugData[1]);
    p["clamped"] = mDebugData[1].w > 0.f;
    p["samplePosition"] = xyz(mDebugData[2]);
    p["irradiance"] = xyz(mDebugData[3]);
    p["selectedProbe"] = mSelectedProbe;
    p["invalidBakeAttempts"] = mInvalidAttempts;
    p["failedBakeSamples"] = mFailedSamples;
    p["firstInvalidProbe"] = mFirstInvalidProbe;
    p["firstInvalidSample"] = mFirstInvalidSample;
    for (uint32_t i = 0; i < 8; ++i)
    {
        const auto suffix = std::to_string(i);
        p["probe" + suffix] = uint32_t(mDebugData[4 + 3 * i].w);
        p["position" + suffix] = xyz(mDebugData[4 + 3 * i]);
        p["weight" + suffix] = mDebugData[5 + 3 * i].x;
        p["visible" + suffix] = mDebugData[5 + 3 * i].y > 0.f;
        p["contribution" + suffix] = xyz(mDebugData[6 + 3 * i]);
    }
    return p;
}

void TraditionalProbeGI::drawDebug(RenderContext* ctx, const ref<Texture>& color)
{
    if (!mpDebugOverlay)
    {
        mpDebugOverlay = RasterPass::create(mpDevice, "RenderPasses/TraditionalProbeGI/ProbeDebug.3d.slang", "vsMain", "psMain");
        auto state = mpDebugOverlay->getState();
        state->setVao(Vao::create(Vao::Topology::TriangleList));
        state->setRasterizerState(RasterizerState::create(RasterizerState::Desc().setCullMode(RasterizerState::CullMode::None)));
        state->setDepthStencilState(DepthStencilState::create(DepthStencilState::Desc().setDepthEnabled(false).setDepthWriteMask(false)));
        mpDebugFbo = Fbo::create(mpDevice);
    }
    mpDebugFbo->attachColorTarget(color, 0);
    mpDebugOverlay->getState()->setFbo(mpDebugFbo);
    auto v = mpDebugOverlay->getRootVar();
    v["gSH"] = mpSH;
    v["gInspection"] = mpDebugData;
    v["gDistance"] = mpDebugDistance;
    auto cb = v["DebugCB"];
    auto camera = mpScene->getCamera();
    cb["gViewProj"] = camera->getViewProjMatrix();
    cb["gCameraPosition"] = camera->getPosition();
    const float3 forward = normalize(camera->getTarget() - camera->getPosition());
    const float3 right = normalize(cross(forward, camera->getUpVector()));
    cb["gCameraRight"] = right;
    cb["gCameraUp"] = normalize(cross(right, forward));
    cb["gCameraForward"] = forward;
    cb["gDimensions"] = float2(color->getWidth(), color->getHeight());
    cb["gCounts"] = mCounts;
    cb["gMin"] = mGridMin;
    cb["gMax"] = mGridMax;
    cb["gSamples"] = mSamples;
    cb["gReady"] = mReady;
    cb["gShowProbes"] = mShowProbes;
    cb["gShowIds"] = mShowIds;
    cb["gOnlyContributors"] = mOnlyContributors;
    cb["gShowBounds"] = mShowBounds;
    cb["gShowLinks"] = mShowLinks;
    cb["gXRay"] = mDebugXRay;
    cb["gPreview"] = mShowProbePreview;
    cb["gRadiance"] = mPreviewRadiance;
    cb["gNegative"] = mShowNegative;
    cb["gSelectedProbe"] = std::min(mSelectedProbe, probeCount() - 1u);
    cb["gRadius"] = mProbeRadius;
    cb["gExposure"] = std::exp2(mDebugExposure);
    ctx->drawInstanced(mpDebugOverlay->getState().get(), mpDebugOverlay->getVars().get(), 6, probeCount() + 23, 0, 0);
}

void TraditionalProbeGI::resetBake()
{
    clearProbes();
    mBaking = true;
    mStatus = "Baking. The completed result will be saved automatically.";
    logInfo("TraditionalProbeGI: BAKE start, {} probes x {} samples, cache {}", probeCount(), mSamples, mCacheFile.string());
}

std::string TraditionalProbeGI::configurationError() const
{
    if (!finite3(mGridMin) || !finite3(mGridMax) || !all(mGridMax > mGridMin))
        return "Invalid bounds: each Grid max must be greater than Grid min.";
    return {};
}

void TraditionalProbeGI::initializeProbes(bool allowAutomatic)
{
    if (!mExplicitBounds)
    {
        const auto& bounds = mpScene->getSceneBounds();
        auto inset = bounds.extent() * 0.05f;
        mGridMin = bounds.minPoint + inset;
        mGridMax = bounds.maxPoint - inset;
    }
    auto path = std::filesystem::weakly_canonical(mpScene->getPath());
    mSceneKey = path.generic_string();
    mSceneStamp = std::filesystem::exists(path) ? int64_t(std::filesystem::last_write_time(path).time_since_epoch().count()) : 0;
    mCacheFile = mConfiguredCacheFile;
    if (mCacheFile.empty())
    {
        uint64_t hash = 14695981039346656037ull;
        for (unsigned char c : mSceneKey)
        {
            hash ^= c;
            hash *= 1099511628211ull;
        }
        std::ostringstream name;
        name << path.stem().string() << '-' << std::hex << hash << ".shprobe";
        mCacheFile = std::filesystem::path("F:/build/probes") / name.str();
    }
    clearProbes();
    mInitialized = true;
    mSettingsChanged = false;
    mStatus = "Waiting: configure the probes, then click Bake or Load matching cache.";
    const auto error = configurationError();
    if (!error.empty())
    {
        mStatus = error;
        if (allowAutomatic && mMode != "manual")
            FALCOR_THROW("{}", error);
        return;
    }
    if (!allowAutomatic || mMode == "manual")
        return;
    bool loaded = false;
    if (mMode != "bake")
        loaded = loadCache();
    if (!loaded)
    {
        FALCOR_CHECK(mMode != "load", "TraditionalProbeGI: cache missing, invalid or incompatible: {}", mCacheFile.string());
        resetBake();
    }
}

bool TraditionalProbeGI::loadCache()
{
    auto reject = [&](const std::string& why)
    {
        mStatus = std::string("Cache not loaded: ") + why + ". Check the settings or click Bake.";
        logWarning("TraditionalProbeGI: cache rejected: {} ({})", why, mCacheFile.string());
        return false;
    };
    std::ifstream in(mCacheFile);
    in.imbue(std::locale::classic());
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
    for (size_t i = 0; i < data.size(); ++i)
    {
        auto& c = data[i];
        in >> c.x >> c.y >> c.z;
        c.w = 0;
        if (!in)
            return reject(fmt::format("{} at SH coefficient {} of {}", in.eof() ? "truncated file" : "invalid numeric data", i, data.size()));
        if (!finite3(float3(c.x, c.y, c.z)))
            return reject(fmt::format("non-finite coefficient {}", i));
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
    mBaking = false;
    mDirty = true;
    mStatus = "Ready: loaded matching probe cache.";
    mDebugRefresh = true;
    logInfo("TraditionalProbeGI: LOAD ready, {} probes, no baking dispatch", probeCount());
    return true;
}

void TraditionalProbeGI::saveCache()
{
    std::vector<float4> data(probeCount() * 9);
    mpSH->getBlob(data.data(), 0, data.size() * sizeof(float4));
    // Validate and serialize everything before touching the existing cache.
    std::ostringstream out;
    out.imbue(std::locale::classic());
    out << std::setprecision(std::numeric_limits<float>::max_digits10);
    out << "FALCOR_PROBE_SH 1\n" << std::quoted(mSceneKey) << '\n' << mSceneStamp << '\n' << std::quoted(mRevision) << '\n';
    out << mCounts.x << ' ' << mCounts.y << ' ' << mCounts.z << ' ' << mSamples << ' ' << mMaxBounces << '\n';
    out << mGridMin.x << ' ' << mGridMin.y << ' ' << mGridMin.z << ' ' << mGridMax.x << ' ' << mGridMax.y << ' ' << mGridMax.z << '\n';
    for (size_t i = 0; i < data.size(); ++i)
    {
        auto c = data[i];
        c /= float(mSamples);
        if (!finite3(float3(c.x, c.y, c.z)))
        {
            mReady = false;
            FALCOR_THROW("Non-finite SH coefficient {} (probe {}). Existing cache was not changed.", i, i / 9);
        }
        out << c.x << ' ' << c.y << ' ' << c.z << '\n';
    }
    FALCOR_CHECK(bool(out), "Failed serializing probe cache.");
    const auto contents = out.str();
    if (!mCacheFile.parent_path().empty()) std::filesystem::create_directories(mCacheFile.parent_path());
    auto temporary = mCacheFile;
    std::random_device random;
    temporary += fmt::format(".tmp-{:08x}{:08x}", random(), random());
    FALCOR_CHECK(!std::filesystem::exists(temporary), "Temporary cache path already exists.");
    try
    {
        std::ofstream file(temporary, std::ios::binary | std::ios::trunc);
        FALCOR_CHECK(bool(file), "Cannot write temporary cache {}", temporary.string());
        file.write(contents.data(), contents.size());
        file.flush();
        FALCOR_CHECK(bool(file), "Failed writing temporary cache {}", temporary.string());
        file.close();
        FALCOR_CHECK(bool(file), "Failed closing temporary cache {}", temporary.string());
#if defined(_WIN32)
        FALCOR_CHECK(MoveFileExW(temporary.c_str(), mCacheFile.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH),
            "Cannot replace probe cache {} (Windows error {}). Existing cache was kept.", mCacheFile.string(), GetLastError());
#else
        std::filesystem::rename(temporary, mCacheFile);
#endif
    }
    catch (...)
    {
        std::error_code ignored;
        std::filesystem::remove(temporary, ignored);
        throw;
    }
    logInfo("TraditionalProbeGI: BAKE complete and SAVED {}", mCacheFile.string());
    mStatus = mInvalidAttempts ? fmt::format("Ready: saved; recovered from {} non-finite path attempts (see log).", mInvalidAttempts)
                              : "Ready: bake completed and saved.";
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
    const bool sceneChanged = mFrame > 0 && is_set(mpScene->getUpdates(), invalidating);
    if (sceneChanged)
    {
        // Existing scene interfaces rebuild shader modules and hit groups when required.
        // Camera movement is not part of the invalidating mask.
        setScene(ctx, mpScene);
        mAllowStartupActions = false;
    }
    if (!mInitialized || mSettingsChanged)
    {
        initializeProbes(mAllowStartupActions && !mSettingsChanged);
        mAllowStartupActions = false;
    }
    if (sceneChanged)
        mStatus = "Scene changed. Pause animations and click Bake to update the probes.";
    const auto action = mAction;
    mAction = Action::None;
    if (action == Action::Cancel)
    {
        clearProbes();
        mStatus = "Bake cancelled. No partial result was saved.";
    }
    else if (action != Action::None)
    {
        const auto error = configurationError();
        if (!error.empty())
            mStatus = error;
        else if (action == Action::Bake)
            resetBake();
        else if (action == Action::Load)
        {
            clearProbes();
            loadCache(); // UI requests report errors in the panel instead of terminating.
        }
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
    var["gBakeHealth"] = mpBakeHealth;
    auto cb = var["ProbeCB"];
    cb["gGridCounts"] = mCounts;
    cb["gGridMin"] = mGridMin;
    cb["gGridMax"] = mGridMax;
    cb["gSampleTotal"] = mSamples;
    cb["gIntensity"] = mIntensity;
    cb["gNormalBias"] = mNormalBias;
    cb["gProbeOnly"] = mProbeOnly;
    cb["gPreviewUnbaked"] = mPreview && !mReady;
    const uint2 debugDims = data.getDefaultTextureDims();
    const bool debugActive = mDebugEnabled && configurationError().empty();
    if (debugActive && (mpDebugDistance->getWidth() != debugDims.x || mpDebugDistance->getHeight() != debugDims.y))
        mpDebugDistance = mpDevice->createTexture2D(debugDims.x, debugDims.y, ResourceFormat::R32Float, 1, 1, nullptr,
            ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess);
    var["gDebugData"] = mpDebugData;
    var["gDebugDistance"] = mpDebugDistance;
    cb["gDebugEnabled"] = debugActive;
    cb["gDebugView"] = mDebugView;
    cb["gInspect"] = false;
    cb["gPick"] = false;
    cb["gPickPixel"] = min(uint2(mPickUV * float2(debugDims)), debugDims - 1u);
    cb["gFrameDim"] = debugDims;
    var["CB"]["gFrameCount"] = mFrame;
    var["CB"]["gPRNGDimension"] = 0u;
    if (mBaking)
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
            const auto health = mpBakeHealth->getElements<uint4>();
            for (uint32_t i = 0; i < health.size(); ++i)
            {
                if (!mInvalidAttempts && health[i].x)
                {
                    mFirstInvalidProbe = i;
                    mFirstInvalidSample = health[i].z - 1u;
                }
                mInvalidAttempts += health[i].x;
                mFailedSamples += health[i].y;
            }
            if (mInvalidAttempts)
                logWarning("TraditionalProbeGI: {} non-finite path attempts, {} unrecovered samples. First: probe {}, sample {}.",
                    mInvalidAttempts, mFailedSamples, mFirstInvalidProbe, mFirstInvalidSample);
            mReady = mFailedSamples == 0;
            mDebugRefresh = true;
            mBaking = false;
            mDirty = true;
            try
            {
                FALCOR_CHECK(mReady, "{} samples failed after bounded retries. First invalid path: probe {}, sample {}. Existing cache was kept.",
                    mFailedSamples, mFirstInvalidProbe, mFirstInvalidSample);
                saveCache();
            }
            catch (const std::exception& e)
            {
                mStatus = std::string(mReady ? "Ready in GPU memory, but saving failed: " : "Bake failed: ") + e.what();
                if (mMode != "manual")
                    throw;
                logWarning("TraditionalProbeGI: {}", mStatus);
            }
        }
    }
    cb["gBake"] = false;
    cb["gReady"] = mReady && mEnable;
    cb["gHasBakedData"] = mReady;
    cb["gPreviewUnbaked"] = mPreview && !mReady;
    if (debugActive && (mPickPending || mDebugRefresh))
    {
        cb["gInspect"] = true;
        cb["gPick"] = mPickPending;
        mpScene->raytrace(ctx, p.get(), mTracer.pVars, uint3(1));
        ctx->uavBarrier(mpDebugData.get());
        mDebugData = mpDebugData->getElements<float4>();
        if (mPickPending && mDebugData[0].w > 0.f)
        {
            float best = -1.f;
            for (uint32_t i = 0; i < 8; ++i)
                if (mDebugData[5 + 3 * i].x > best)
                {
                    best = mDebugData[5 + 3 * i].x;
                    mSelectedProbe = uint32_t(mDebugData[4 + 3 * i].w);
                }
        }
        mPickPending = mDebugRefresh = false;
        cb["gInspect"] = false;
        cb["gPick"] = false;
    }
    mpScene->raytrace(ctx, p.get(), mTracer.pVars, uint3(data.getDefaultTextureDims(), 1));
    if (debugActive) drawDebug(ctx, data.getTexture("color"));
    if (mDirty)
    {
        auto& dict = data.getDictionary();
        auto flags = dict.getValue(kRenderPassRefreshFlags, RenderPassRefreshFlags::None);
        dict[kRenderPassRefreshFlags] = flags | RenderPassRefreshFlags::RenderOptionsChanged;
        mDirty = false;
    }
    ++mFrame;
}

void TraditionalProbeGI::configureBake(const Properties& props)
{
    auto counts = mCounts;
    auto lo = mGridMin, hi = mGridMax;
    auto samples = mSamples, batch = mBatch, bounces = mMaxBounces;
    auto revision = mRevision;
    auto explicitBounds = mExplicitBounds;
    for (const auto& [key, value] : props)
    {
        if (key == "gridCounts")
            counts = value;
        else if (key == "gridMin")
        {
            lo = value;
            explicitBounds = true;
        }
        else if (key == "gridMax")
        {
            hi = value;
            explicitBounds = true;
        }
        else if (key == "autoBounds")
            explicitBounds = !value.operator bool();
        else if (key == "samplesPerProbe")
            samples = value;
        else if (key == "samplesPerFrame")
            batch = value;
        else if (key == "maxBounces")
            bounces = value;
        else if (key == "sceneRevision")
            revision = value.operator std::string();
        else
            FALCOR_THROW("Unknown bake setting '{}'", key);
    }
    FALCOR_CHECK(all(counts >= uint3(2)) && all(counts <= uint3(32)), "gridCounts must be 2..32 per axis.");
    FALCOR_CHECK(samples >= 1 && samples <= 65536 && batch >= 1 && batch <= 64 && bounces <= 8, "Invalid sampling settings.");
    // Bounds may be temporarily inverted while typing. The UI rejects Bake/Load until fixed.
    const bool changed = any(counts != mCounts) || any(lo != mGridMin) || any(hi != mGridMax) || samples != mSamples ||
                         bounces != mMaxBounces || revision != mRevision || explicitBounds != mExplicitBounds;
    mCounts = counts;
    mGridMin = lo;
    mGridMax = hi;
    mSamples = samples;
    mBatch = batch;
    mMaxBounces = bounces;
    mRevision = revision;
    mExplicitBounds = explicitBounds;
    if (changed)
    {
        mSettingsChanged = true;
        mReady = false;
        mBaking = false;
        mCompleted = 0;
        mAction = Action::None;
        mDirty = true;
        mStatus = "Bake settings changed. Click Bake to apply them.";
    }
}

void TraditionalProbeGI::renderUI(Gui::Widgets& w)
{
    if (!mpScene)
    {
        w.text("Load a scene using File > Load Scene.");
        return;
    }
    w.text("Scene: " + mpScene->getPath().filename().string());
    w.textWrapped(mStatus);
    if (mInvalidAttempts) w.text(fmt::format("Numerical path attempts rejected: {}; failed samples: {}", mInvalidAttempts, mFailedSamples));
    if (!mReady && mPreview)
        w.text("Unbaked material preview (not probe lighting)");
    w.text(std::to_string(mCompleted) + " / " + std::to_string(mSamples) + " samples per probe");
    auto counts = mCounts;
    auto samples = mSamples, batch = mBatch, bounces = mMaxBounces;
    auto lo = mGridMin, hi = mGridMax;
    bool automatic = !mExplicitBounds;
    auto revision = mRevision;
    Properties changes;
    if (w.var("Grid counts XYZ", counts, 2u, 32u))
        changes["gridCounts"] = counts;
    if (w.checkbox("Fit bounds to scene", automatic))
        changes["autoBounds"] = automatic;
    if (!automatic)
    {
        if (w.var("Grid min", lo))
            changes["gridMin"] = lo;
        if (w.var("Grid max", hi))
            changes["gridMax"] = hi;
    }
    if (w.var("Samples per probe", samples, 1u, 65536u))
        changes["samplesPerProbe"] = samples;
    if (w.var("Samples per frame", batch, 1u, 64u))
        changes["samplesPerFrame"] = batch;
    w.tooltip("Controls baking work per frame. Changing this preserves completed samples.");
    if (w.var("Max bounces", bounces, 0u, 8u))
        changes["maxBounces"] = bounces;
    if (w.textbox("Scene revision", revision))
        changes["sceneRevision"] = revision;
    configureBake(changes);
    w.text(std::to_string(probeCount()) + " probes, " + std::to_string(uint64_t(probeCount()) * mSamples) + " total paths");
    w.text("Cache: " + mCacheFile.string());
    const auto error = configurationError();
    if (!error.empty())
        w.text(error);
    else
    {
        if (w.button(mBaking ? "Restart bake" : "Bake"))
            requestBake();
        if (!mBaking && w.button("Load matching cache"))
            requestLoad();
    }
    if (mBaking && w.button("Cancel bake"))
        cancelBake();
    mDirty |= w.checkbox("Preview unbaked surfaces", mPreview);
    mDirty |= w.checkbox("Enable probes", mEnable);
    mDirty |= w.checkbox("Probe lighting only", mProbeOnly);
    mDirty |= w.var("Probe intensity", mIntensity, 0.f, 10.f);
    if (w.var("Normal bias", mNormalBias, 0.f, 1.f)) mDirty = mDebugRefresh = true;
    w.text("Static diffuse SH. No visibility correction; thin-wall light leaks are expected.");
    if (auto d = w.group("Debugging"))
    {
        if (d.checkbox("Enable debug", mDebugEnabled)) mDirty = mDebugRefresh = true;
        if (mDebugEnabled)
        {
            if (!configurationError().empty()) d.text("Debug paused: fix the invalid grid bounds first.");
            const Gui::DropdownList views = {{0, "Normal lighting"}, {1, "Irradiance (no albedo)"},
                {2, "Diffuse albedo"}, {3, "World normal"}, {4, "Probe cell"}, {5, "Grid clamp mask"}};
            mDirty |= d.dropdown("Surface view", views, mDebugView);
            d.checkbox("Show probe spheres", mShowProbes);
            d.checkbox("Show probe IDs", mShowIds);
            d.checkbox("Only selected cell probes", mOnlyContributors);
            d.checkbox("Show grid bounds", mShowBounds);
            d.checkbox("X-ray overlays", mDebugXRay);
            d.var("Sphere radius / spacing", mProbeRadius, 0.01f, 0.3f);
            d.checkbox("Pick surface (right click)", mPickEnabled);
            d.tooltip("Right click selects a surface instead of 6DoF camera roll. Left drag still controls the camera.");
            d.checkbox("Show contribution links", mShowLinks);
            if (d.button("Clear selection")) clearDebugSelection();
            if (d.button("Refresh inspection")) mDebugRefresh = true;
            d.text("Links: green visible, red blocked; yellow = normal-bias offset.");
            d.text("Visibility is diagnostic only; production weights are unchanged.");
            if (mDebugData[0].w > 0.f)
            {
                d.text(fmt::format("Surface ({:.3f}, {:.3f}, {:.3f}); clamped: {}", mDebugData[0].x,
                    mDebugData[0].y, mDebugData[0].z, mDebugData[1].w > 0.f ? "yes" : "no"));
                for (uint32_t i = 0; i < 8; ++i)
                {
                    auto a = mDebugData[4 + 3 * i], b = mDebugData[5 + 3 * i], c = mDebugData[6 + 3 * i];
                    d.text(fmt::format("#{} w={:.4f} {} weighted E=({:.3f},{:.3f},{:.3f})", uint32_t(a.w), b.x,
                        b.y > 0.f ? "visible" : "BLOCKED", c.x, c.y, c.z));
                    d.text(fmt::format("  pos=({:.3f},{:.3f},{:.3f})", a.x, a.y, a.z));
                }
            }
            else d.text("No surface selected. Enable Pick surface, then click the scene.");
            d.checkbox("Selected probe direction sphere", mShowProbePreview);
            d.var("Selected probe ID", mSelectedProbe, 0u, probeCount() - 1u);
            d.checkbox("Sphere shows radiance", mPreviewRadiance);
            d.checkbox("Highlight negative SH (magenta)", mShowNegative);
            d.var("Sphere exposure (EV)", mDebugExposure, -10.f, 10.f);
            d.text("Direction sphere: camera-facing world directions; radiance is an L2 SH reconstruction.");
            if (!mReady) d.text("No completed bake: gray spheres, irradiance view is black.");
        }
    }
}

void TraditionalProbeGI::setScene(RenderContext* pRenderContext, const ref<Scene>& pScene)
{
    clearDebugSelection();
    if (pScene && mHasScene && pScene != mpScene)
        mExplicitBounds = false;
    if (pScene)
        mHasScene = true;
    mInitialized = false;
    mReady = false;
    mBaking = false;
    mCompleted = 0;
    mSettingsChanged = false;
    mAllowStartupActions = true;
    mStatus = "Waiting: configure the probes, then click Bake.";
    mpSH = nullptr;
    mAction = Action::None;
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
