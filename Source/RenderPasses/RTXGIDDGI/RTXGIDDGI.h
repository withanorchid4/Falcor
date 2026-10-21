#pragma once
#include "Falcor.h"
#include "RenderGraph/RenderPass.h"
#include "Utils/Sampling/SampleGenerator.h"
#include "Core/Pass/ComputePass.h"
#include "Rendering/Lights/EnvMapSampler.h"
#include <random>

using namespace Falcor;

/** Dynamic diffuse GI using the original RTXGI-DDGI 1.3.7 SDK shaders.
 * Falcor owns resources and dispatches; no static SH cache is used.
 */
class RTXGIDDGI : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(RTXGIDDGI, "RTXGIDDGI", "Dynamic diffuse probe GI (NVIDIA RTXGI-DDGI 1.3.7).");
    static ref<RTXGIDDGI> create(ref<Device> device, const Properties& properties)
    {
        return make_ref<RTXGIDDGI>(device, properties);
    }
    RTXGIDDGI(ref<Device> device, const Properties& properties);
    Properties getProperties() const override;
    void setProperties(const Properties& properties) override;
    RenderPassReflection reflect(const CompileData& data) override;
    void execute(RenderContext* context, const RenderData& data) override;
    void renderUI(Gui::Widgets& widgets) override;
    void setScene(RenderContext* context, const ref<Scene>& scene) override;
    void onSceneUpdates(RenderContext* context, IScene::UpdateFlags flags) override;
    void reset() { mResetPending = true; }
    uint32_t getUpdatedFrames() const { return mUpdatedFrames; }
    const std::string& getStatus() const { return mStatus; }
    Properties getStats() const;

private:
    struct Options
    {
        uint3 counts = uint3(8, 6, 8);
        uint32_t rays = 256;
        float hysteresis = 0.97f;
        float normalBias = 0.05f;
        float viewBias = 0.05f;
        float intensity = 1.f;
        float3 gridMin = float3(-1.f);
        float3 gridMax = float3(1.f);
        bool autoBounds = true;
        bool relocation = true;
        bool classification = true;
        bool update = true;
        bool enableGI = true;
        bool showProbes = false;
        bool indirectOnly = false;
        bool useRTXDI = true;
    } mOptions;
    struct RayProgram
    {
        ref<Program> program;
        ref<RtBindingTable> table;
        ref<RtProgramVars> vars;
    } mTrace, mRender;

    void createPrograms();
    void allocateResources(RenderContext* context);
    void clearHistory(RenderContext* context);
    void uploadConstants();
    void bindRayProgram(RayProgram& ray, const RenderData& data);
    void updateProbes(RenderContext* context);
    ref<Scene> mpScene;
    ref<SampleGenerator> mpSampleGenerator;
    ref<Buffer> mpVolume;
    ref<Buffer> mpDiagnostics;
    std::unique_ptr<EnvMapSampler> mpEnvMapSampler;
    ref<EnvMap> mpSamplerSource;
    ref<Texture> mpRayData, mpIrradiance, mpDistance, mpProbeData, mpVariability;
    ref<Sampler> mpSampler;
    ref<ComputePass> mpBlendIrradiance, mpBlendDistance, mpRelocate, mpClassify;
    float3 mGridMin = float3(0.f), mGridMax = float3(0.f), mSpacing = float3(1.f);
    uint32_t mFrame = 0, mUpdatedFrames = 0;
    bool mSupported = true;
    bool mHasDirectLighting = false;
    bool mReallocate = true, mRebuildPrograms = true, mResetPending = true, mOptionsChanged = true;
    std::string mStatus = "Load a scene to start DDGI.";
    std::mt19937 mRandom{1337};
};
