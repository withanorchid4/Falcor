#pragma once
#include "Falcor.h"
#include "Core/Pass/RasterPass.h"
#include "Core/Pass/ComputePass.h"
#include "RenderGraph/RenderPass.h"
#include "Utils/Sampling/SampleGenerator.h"

using namespace Falcor;

class TraditionalProbeGI : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(TraditionalProbeGI, "TraditionalProbeGI", "Baked regular-grid diffuse SH light probes.");
    static ref<TraditionalProbeGI> create(ref<Device> device, const Properties& props)
    {
        return make_ref<TraditionalProbeGI>(device, props);
    }
    TraditionalProbeGI(ref<Device> device, const Properties& props);
    Properties getProperties() const override;
    RenderPassReflection reflect(const CompileData&) override;
    void setScene(RenderContext*, const ref<Scene>&) override;
    void execute(RenderContext*, const RenderData&) override;
    void renderUI(Gui::Widgets&) override;
    bool onMouseEvent(const MouseEvent&) override;
    void configureDebug(const Properties& props);
    void pickSurface(float2 uv);
    void inspectSurfacePoint(float3 position, float3 normal);
    Properties getDebugInfo() const;
    void configureBake(const Properties& props);
    void configureVisibility(const Properties& props);
    void applyLeakResistantPreset();
    void requestBake() { mAction = Action::Bake; }
    void requestLoad() { mAction = Action::Load; }
    void cancelBake() { mAction = Action::Cancel; }
    bool isReady() const { return mReady; }
    bool isBaking() const { return mBaking; }
    uint32_t getCompletedSamples() const { return mCompleted; }
    uint32_t getCompletedDistanceSamples() const { return mDistanceCompleted; }
    const std::string& getStatus() const { return mStatus; }
    std::string getCacheFile() const { return mCacheFile.string(); }

private:
    void prepareVars();
    void initializeProbes(bool allowAutomatic);
    std::filesystem::path automaticCacheFile(bool legacy = false) const;
    void clearProbes();
    std::string configurationError() const;
    void resetBake();
    bool loadCache();
    void saveCache();
    uint2 distanceAtlasSize() const;
    void clearDebugSelection();
    void drawDebug(RenderContext*, const ref<Texture>& color);
    uint32_t probeCount() const { return mCounts.x * mCounts.y * mCounts.z; }
    uint32_t distanceSampleTarget() const { return mDistanceBakeMode == "angular" ? mDistanceRays : mDistanceSamples; }

    ref<Scene> mpScene;
    ref<SampleGenerator> mpSampleGenerator;
    struct
    {
        ref<Program> pProgram;
        ref<RtBindingTable> pBindingTable;
        ref<RtProgramVars> pVars;
    } mTracer;
    ref<Buffer> mpSH;
    ref<Texture> mpDistanceMoments;
    ref<Buffer> mpDistanceRays;
    ref<ComputePass> mpDistanceBlend;
    std::string mDistanceBakeMode = "texelLocal";
    uint32_t mDistanceRays = 2048;
    float mDistanceExponent = 50.f;
    uint32_t mDistanceResolution = 14;
    uint32_t mDistanceSamples = 16, mDistanceCompleted = 0, mDistanceTexelOffset = 0;
    uint32_t mDistanceSweepBatch = 0;
    float mDistanceRangeScale = 2.f, mDistanceMax = 1.f;
    bool mUseVisibility = true, mUseNormalWeight = true;
    bool mDistanceBilinear = true;
    bool mDistanceSmooth = false, mNormalHemisphere = false;
    std::string mVisibilityMode = "moments";
    float mVisibilityPower = 3.f, mVarianceBase = 1e-6f;
    ref<Buffer> mpBakeHealth;
    uint64_t mInvalidAttempts = 0, mFailedSamples = 0;
    uint32_t mFirstInvalidProbe = 0, mFirstInvalidSample = 0;
    ref<Buffer> mpDebugData;
    ref<Texture> mpDebugDistance;
    ref<RasterPass> mpDebugOverlay;
    ref<Fbo> mpDebugFbo;
    std::vector<float4> mDebugData = std::vector<float4>(52, float4(0));
    bool mDebugEnabled = false, mPickEnabled = false, mPickPending = false, mDebugRefresh = false;
    bool mShowProbes = true, mShowBounds = true, mShowLinks = true, mShowIds = false, mDebugXRay = false;
    bool mOnlyContributors = false;
    bool mShowProbePreview = true, mPreviewRadiance = false, mShowNegative = false;
    uint32_t mDebugView = 0, mSelectedProbe = 0;
    float mProbeRadius = 0.08f, mDebugExposure = 0.f;
    float2 mPickUV = float2(0.5f);
    uint3 mCounts = uint3(8, 6, 8);
    float3 mGridMin = {}, mGridMax = {};
    bool mExplicitBounds = false;
    uint32_t mSamples = 2048, mBatch = 16, mMaxBounces = 3;
    uint32_t mCompleted = 0, mFrame = 0;
    enum class Action
    {
        None,
        Bake,
        Load,
        Cancel
    };
    Action mAction = Action::None;
    bool mInitialized = false, mReady = false, mDirty = true, mBaking = false;
    bool mSettingsChanged = false, mAllowStartupActions = true, mHasScene = false;
    bool mPreview = true;
    bool mEnable = true, mProbeOnly = false;
    float mIntensity = 1.f, mNormalBias = 0.05f, mViewBias = 0.f;
    std::string mMode = "manual", mRevision = "1", mSceneKey;
    std::string mStatus = "Load a scene to configure probes.";
    int64_t mSceneStamp = 0;
    std::filesystem::path mConfiguredCacheFile, mCacheFile;
};
