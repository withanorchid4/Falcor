#pragma once
#include "Falcor.h"
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
    void configureBake(const Properties& props);
    void requestBake() { mAction = Action::Bake; }
    void requestLoad() { mAction = Action::Load; }
    void cancelBake() { mAction = Action::Cancel; }
    bool isReady() const { return mReady; }
    bool isBaking() const { return mBaking; }
    uint32_t getCompletedSamples() const { return mCompleted; }
    const std::string& getStatus() const { return mStatus; }
    std::string getCacheFile() const { return mCacheFile.string(); }

private:
    void prepareVars();
    void initializeProbes(bool allowAutomatic);
    void clearProbes();
    std::string configurationError() const;
    void resetBake();
    bool loadCache();
    void saveCache();
    uint32_t probeCount() const { return mCounts.x * mCounts.y * mCounts.z; }

    ref<Scene> mpScene;
    ref<SampleGenerator> mpSampleGenerator;
    struct
    {
        ref<Program> pProgram;
        ref<RtBindingTable> pBindingTable;
        ref<RtProgramVars> pVars;
    } mTracer;
    ref<Buffer> mpSH;
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
    float mIntensity = 1.f, mNormalBias = 0.05f;
    std::string mMode = "manual", mRevision = "1", mSceneKey;
    std::string mStatus = "Load a scene to configure probes.";
    int64_t mSceneStamp = 0;
    std::filesystem::path mConfiguredCacheFile, mCacheFile;
};
