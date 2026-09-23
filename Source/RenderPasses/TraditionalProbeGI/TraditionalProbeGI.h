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

private:
    void prepareVars();
    void initializeProbes();
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
    bool mInitialized = false, mReady = false, mDirty = true, mRebake = false;
    bool mEnable = true, mProbeOnly = false;
    float mIntensity = 1.f, mNormalBias = 0.05f;
    std::string mMode = "auto", mRevision = "1", mSceneKey;
    int64_t mSceneStamp = 0;
    std::filesystem::path mCacheFile = "F:/build/probes/default.shprobe";
};
