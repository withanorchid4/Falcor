#pragma once
#include "Falcor.h"
#include "RenderGraph/RenderPass.h"
#include "Utils/Sampling/SampleGenerator.h"
#include "Core/Pass/ComputePass.h"
#include "Core/Pass/RasterPass.h"
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
        bool useWRC = false;
        bool wrcGroupByMaterial = true;
        uint32_t wrcStressMode = 0; // Experiment: 0 off, 1 common loop, 2 distinct loops per type.
        uint32_t wrcStressIterations = 0;
        bool wrcStressStats = false; // Wave diagnostics; disable during GPU timing.
        float wrcCellScale = 0.1f;
        float wrcLodDistance = 8.f; // In units of the smallest probe spacing.
        uint32_t wrcMaxLod = 16;
        uint32_t wrcProbeLimit = 16;
        uint32_t wrcTableSize = 65536;
        uint32_t wrcMaxAge = 0;
        uint32_t wrcShadeSamples = 1;
        bool wrcBypassSharing = false; // Validation: split dispatches with original per-ray shading.
        bool showWrcCells = false;
        bool wrcCellsXRay = false;
        uint32_t wrcCellsLod = 0; // 0 shows every occupied LOD.
        float wrcCellsOpacity = 0.65f;
    } mOptions;
    struct RayProgram
    {
        ref<Program> program;
        ref<RtBindingTable> table;
        ref<RtProgramVars> vars;
    } mTrace, mRender;
    RayProgram mWrcTrace;
    ref<ComputePass> mpWrcBuild, mpWrcPrepare, mpWrcShade, mpWrcGather;
    uint32_t mWrcTypeCount = 0;
    uint32_t getWrcDispatchCount() const { return mOptions.wrcGroupByMaterial ? mWrcTypeCount : 1u; }

    void buildRayProgram(RayProgram& ray, const char* shader, const char* entry);
    void createPrograms();
    void allocateWrcResources();
    void clearWrc(RenderContext* context);
    void bindWrcProgram(RayProgram& ray, const RenderData& data);
    void bindWrcResources(const ShaderVar& root, uint32_t shaderBucket = 0);
    void bindWrcCompute(RenderContext* context, const ref<ComputePass>& pass, const RenderData& data, uint32_t shaderBucket = 0);
    ref<ComputePass> createWrcCompute(const char* entry);
    void traceWithWrc(RenderContext* context, const RenderData& data);
    void drawWrcCells(RenderContext* context, const ref<Texture>& color);
    void allocateResources(RenderContext* context);
    void clearHistory(RenderContext* context);
    void uploadConstants();
    void bindRayProgram(RayProgram& ray, const RenderData& data);
    void updateProbes(RenderContext* context);
    ref<Scene> mpScene;
    ref<SampleGenerator> mpSampleGenerator;
    ref<Buffer> mpVolume;
    ref<Buffer> mpDiagnostics;
    ref<Buffer> mpWrcHits, mpWrcOwners, mpWrcKeys, mpWrcRadiance, mpWrcLastUpdate, mpWrcCounters;
    ref<Buffer> mpWrcRaySlots, mpWrcActiveSlots, mpWrcActiveCounts, mpWrcDispatchArgs, mpWrcTypeMap;
    ref<ComputePass> mpWrcDebugPrepare;
    ref<RasterPass> mpWrcDebugDraw;
    ref<Buffer> mpWrcDebugArgs;
    ref<Texture> mpWrcDebugDepth;
    ref<Fbo> mpWrcDebugFbo;
    bool mWrcReallocate = true, mWrcResetPending = true;
    uint64_t mWrcInvalidations = 0, mWrcAllocatedBytes = 0;
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
