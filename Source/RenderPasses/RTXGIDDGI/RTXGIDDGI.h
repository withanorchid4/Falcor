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
        bool batchProbeUpdates = false;
        bool wrapProbeBatches = false; // Fill the frame budget across the end of the probe grid.
        uint32_t probesPerFrame = 1024;
        float hysteresis = 0.97f;
        float normalBias = 0.05f;
        float viewBias = 0.05f;
        float minFrontfaceDistance = 0.10f; // Fraction of the minimum probe spacing, like the bias properties.
        float intensity = 1.f;
        float3 gridMin = float3(-1.f);
        float3 gridMax = float3(1.f);
        bool autoBounds = true;
        bool relocation = true;
        bool classification = true;
        bool update = true;
        bool enableGI = true;
        bool worldCache = false;
        bool sharc = false; // Independent SHaRC backend within the shared world-cache/FG host.
        float sharcSceneScale = 20.f;
        uint32_t worldCacheDownsample = 8, worldCacheBounces = 3, worldCacheHistory = 16;
        float worldCacheDensity = 20.f, worldCacheMaxIntensity = 0.f;
        bool finalGather = false;
        bool hoistNormalOct = true;
        bool skipDirectionNormalize = true;
        bool tetrahedralInterpolation = false; // Optional four-corner query; default SDK eight-corner interpolation.
        bool primaryShadingNormalCorrection = true; // Diagnostic A/B override; still honors the GBuffer policy.
        bool halfResolutionGather = false;
        bool jitterHalfGather = false;
        bool restirGather = false;
        bool restirTemporal = true;
        bool restirSpatial = true;
        bool restirSpatialFeedback = false; // Feed the final spatial reservoir into next-frame temporal reuse.
        bool restirTemporalCellMapping = true; // Prefer the reprojected coarse cell before searching neighbors.
        bool restirBiasCorrection = true;
        bool restirFullResolution = false;
        uint32_t restirSpatialSamples = 4;
        uint32_t restirSpatialPasses = 2;
        uint32_t restirIntegrateSamples = 16;
        float restirIntegrateRadius = 3.f;
        float restirSpatialRadius = 8.f;
        uint32_t restirMaxAge = 0; // Optional sample-age limit; disabled to preserve the static gather baseline.
        uint32_t restirHistoryLength = 20; // Effective candidate count, including the fresh candidate.
        bool gatherDiffuse = true;
        bool gatherSpecular = true;
        bool showProbes = false;
        bool indirectOnly = false;
        bool useRTXDI = true;
        bool useWRC = false; // idTech 8 world radiance cache; DDGI + final gather only.
        bool wrcScreenCache = true; // Final gather reads the previous frame's gather pixels first.
        bool wrcGroupByMaterial = false; // Measured slower than one mixed dispatch (docs/IdTech8).
        uint32_t wrcStressMode = 0; // Experiment: 0 off, 1 common loop, 2 distinct loops per type.
        uint32_t wrcStressIterations = 0;
        bool wrcStressStats = false; // Wave diagnostics; disable during GPU timing.
        float wrcCellSize = 0.25f;   // Base cell width in world units (idTech 8: 25 cm).
        float wrcLodDistance = 8.f;  // World units; must stay below 64 cells for 8-bit wrapped keys.
        uint32_t wrcMaxLod = 64;
        uint32_t wrcProbeLimit = 16;
        uint32_t wrcTableSize = 262144; // Sponza fills ~51k slots per update; keep load below ~25%.
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
    } mTrace, mRender, mHalfGather;
    RayProgram mWrcTrace;
    ref<ComputePass> mpWrcBuild, mpWrcPrepare, mpWrcShade, mpWrcGather;
    uint32_t mWrcTypeCount = 0;
    uint32_t getWrcDispatchCount() const { return mOptions.wrcGroupByMaterial ? mWrcTypeCount : 1u; }
    // WRC exists only for DDGI + (non-ReSTIR) final gather; setProperties enforces it.
    bool wrcActive() const { return mOptions.useWRC && mOptions.finalGather && !mOptions.restirGather && !mOptions.worldCache; }
    bool screenCacheActive() const { return wrcActive() && mOptions.wrcScreenCache && mOptions.enableGI; }
    void bindWrcLookup(const ShaderVar& root);
    void prepareScreenCache(const uint2& frameDim);
    float3 mWrcCamera = float3(0.f); // Camera of the latest WRC update; keys depend on it.
    ref<Texture> mpScreenCacheColor[2], mpScreenCachePos[2];
    uint32_t mScreenCacheWrite = 0;
    bool mScreenCacheValid = false, mScreenCacheHalf = false;
    float4x4 mScreenCachePrevViewProj = float4x4::identity();
    float3 mScreenCachePrevCamera = float3(0.f);
    uint2 mScreenCachePrevOffset = uint2(0);
    ref<Buffer> mpFgCacheCounters;

    void prepareWorldCache(RenderContext* context);
    void prepareSharc(RenderContext* context);
    void bindSharc(const ShaderVar& root);
    void updateSharc(RenderContext* context, const RenderData& data);
    ref<Buffer> mpSharcHash, mpSharcAccum, mpSharcResolved, mpSharcStats;
    float3 mSharcPreviousCamera = float3(0.f);
    void updateWorldCache(RenderContext* context, const RenderData& data);
    void bindWorldCache(const ShaderVar& root);
    void renderWorldCacheUI(Gui::Widgets& widgets);
    RayProgram mWorldCacheTrace;
    ref<ComputePass> mpWorldCacheResolve;
    ref<Buffer> mpWCState, mpWCKeys, mpWCLighting, mpWCAccumulation, mpWCAge, mpWCStats;
    bool mWorldCacheReset = true;
    uint32_t mWorldCacheFrames = 0;
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
    void drawProbeVisualization(RenderContext* context, const RenderData& data);
    ref<ComputePass> mpProbeVisUpdate, mpProbeVisDraw;
    ref<Buffer> mpProbeVisBounds, mpProbeVisBlasBuffer, mpProbeVisBlasScratch;
    ref<Buffer> mpProbeVisInstances, mpProbeVisTlasBuffer, mpProbeVisTlasScratch;
    ref<RtAccelerationStructure> mpProbeVisBlas, mpProbeVisTlas;
    uint32_t mProbeVisCount = 0;
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
    uint32_t mProbeCursor = 0, mProbeBatchCount = 0, mProbeSweeps = 0;
    uint32_t mLastProbeBatchStart = 0, mLastProbeBatchCount = 0;
    uint64_t mProbeUpdatesTotal = 0;
    uint2 mGatherOffset = uint2(0);
    RayProgram mRestirInitialProgram, mRestirTemporalProgram, mRestirSpatialProgram, mRestirIntegrateProgram;
    ref<Buffer> mpRestirInitial, mpRestirTemporal, mpRestirSpatial, mpRestirHistory;
    ref<Buffer> mpRestirInput, mpRestirOutput;
    uint2 mRestirDim = uint2(0), mRestirPreviousOffset = uint2(0);
    float4x4 mRestirPreviousViewProj = float4x4::identity();
    uint32_t mRestirSpatialPassIndex = 0;
    bool mRestirHistoryValid = false;
    bool restirActive() const { return mOptions.restirGather && mOptions.finalGather && mOptions.enableGI; }
    bool mRestirResetPending = true;
    uint64_t mRestirResetCount = 0;
    bool mSupported = true;
    bool mHasDirectLighting = false;
    bool mReallocate = true, mRebuildPrograms = true, mResetPending = true, mOptionsChanged = true;
    std::string mStatus = "Load a scene to start DDGI.";
    std::mt19937 mRandom{1337};
};
