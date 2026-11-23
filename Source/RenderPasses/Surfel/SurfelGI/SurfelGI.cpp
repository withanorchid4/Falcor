#include "SurfelGI.h"
#include "RenderGraph/RenderPassStandardFlags.h"
#include "Utils/Math/FalcorMath.h"
#include "SurfelTypes.slang"

namespace
{

float plotFunc(void* data, int i)
{
    return static_cast<float*>(data)[i];
}

const std::string kPackedHitInfoTextureName = "packedHitInfo";
const std::string kOutputTextureName = "output";
const std::string kIrradianceMapTextureName = "irradiance map";
const std::string kSurfelDepthTextureName = "surfel depth";

const std::string kSurfelBufferVarName = "gSurfelBuffer";
const std::string kSurfelGeometryBufferVarName = "gSurfelGeometryBuffer";
const std::string kSurfelValidIndexBufferVarName = "gSurfelValidIndexBuffer";
const std::string kSurfelDirtyIndexBufferVarName = "gSurfelDirtyIndexBuffer";
const std::string kSurfelFreeIndexBufferVarName = "gSurfelFreeIndexBuffer";
const std::string kCellInfoBufferVarName = "gCellInfoBuffer";
const std::string kCellToSurfelBufferVarName = "gCellToSurfelBuffer";
const std::string kSurfelRayResultBufferVarName = "gSurfelRayResultBuffer";
const std::string kSurfelRecycleInfoBufferVarName = "gSurfelRecycleInfoBuffer";
const std::string kSurfelReservationBufferVarName = "gSurfelReservationBuffer";
const std::string kSurfelRefCounterVarName = "gSurfelRefCounter";
const std::string kSurfelCounterVarName = "gSurfelCounter";

} // namespace

SurfelGI::SurfelGI(ref<Device> pDevice, const Properties& props) : RenderPass(pDevice)
{
    mpDevice = pDevice;
    setProperties(props);
    mTempStaticParams = mStaticParams;

    if (!mpDevice->isShaderModelSupported(ShaderModel::SM6_5))
        FALCOR_THROW("SurfelGI requires Shader Model 6.5 support.");
    if (!mpDevice->isFeatureSupported(Device::SupportedFeatures::RaytracingTier1_1))
        FALCOR_THROW("SurfelGI requires Raytracing Tier 1.1 support.");

    mpFence = mpDevice->createFence();
    mpSampleGenerator = SampleGenerator::create(mpDevice, SAMPLE_GENERATOR_UNIFORM);

    // Create sampler.
    Sampler::Desc samplerDesc;
    samplerDesc.setFilterMode(TextureFilteringMode::Linear, TextureFilteringMode::Linear, TextureFilteringMode::Linear);
    samplerDesc.setAddressingMode(TextureAddressingMode::Clamp, TextureAddressingMode::Clamp, TextureAddressingMode::Clamp);
    mpSurfelDepthSampler = mpDevice->createSampler(samplerDesc);
}

RenderPassReflection SurfelGI::reflect(const CompileData& compileData)
{
    RenderPassReflection reflector;

    reflectInput(reflector, compileData.defaultTexDims);
    reflectOutput(reflector, compileData.defaultTexDims);

    if (math::any(mFrameDim != compileData.defaultTexDims))
    {
        mIsFrameDimChanged = true;
        mFrameDim = compileData.defaultTexDims;
    }

    return reflector;
}

void SurfelGI::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    if (!mpScene)
        return;

    if (mResetSurfelBuffer) {
        createResolutionIndependentResources();
        mFrameIndex = 0; mResetSurfelBuffer = false; mOptionsChanged = true;
    }
    if (mOptionsChanged) {
        auto& dict = renderData.getDictionary();
        auto flags = dict.getValue(kRenderPassRefreshFlags, RenderPassRefreshFlags::None);
        dict[kRenderPassRefreshFlags] = flags | RenderPassRefreshFlags::RenderOptionsChanged;
        mOptionsChanged = false;
    }
    if (mRecompile)
    {
        createPasses();
        createResolutionIndependentResources();

        mRecompile = false;
    }

    if (mIsFrameDimChanged)
    {
        createResolutionDependentResources();
        mIsFrameDimChanged = false;
    }

    bindResources(renderData);
    if (mFrameIndex == 0) {
        pRenderContext->clearUAV(mpIrradianceMapTexture->getUAV().get(), float4(0));
        pRenderContext->clearUAV(mpSurfelDepthTexture->getUAV().get(), float4(0));
        pRenderContext->clearUAV(mpSurfelBuffer->getUAV().get(), uint4(0));
        pRenderContext->clearUAV(mpEmptySurfelBuffer->getUAV().get(), uint4(0));
        pRenderContext->clearUAV(mpSurfelRefCounter->getUAV().get(), uint4(0));
    }
    pRenderContext->clearUAV(mpCellInfoBuffer->getUAV().get(), uint4(0));
    pRenderContext->clearUAV(mpSurfelReservationBuffer->getUAV().get(), uint4(0));

    mFOVy = focalLengthToFovY(mpScene->getCamera()->getFocalLength(), mpScene->getCamera()->getFrameHeight());
    mCamPos = mpScene->getCamera()->getPosition();

    // Request the light collection if emissive lights are enabled.
    if (mpScene->getRenderSettings().useEmissiveLights)
        mpScene->getLightCollection(pRenderContext);

    {
        FALCOR_PROFILE(pRenderContext, "Prepare Pass");

        mpPreparePass->execute(pRenderContext, uint3(1));
        pRenderContext->copyResource(mpSurfelDirtyIndexBuffer.get(), mpSurfelValidIndexBuffer.get());
    }

    {
        FALCOR_PROFILE(pRenderContext, "Update Pass (Collect Cell Info Pass)");

        auto var = mpCollectCellInfoPass->getRootVar();

        mpScene->bindShaderDataForRaytracing(pRenderContext, var["gScene"], 0);

        var["CB"]["gCameraPos"] = mCamPos;
        var["CB"]["gResolution"] = mFrameDim;
        var["CB"]["gFOVy"] = mFOVy;
        var["CB"]["gLockSurfel"] = mLockSurfel;
        var["CB"]["gVarianceSensitivity"] = mRuntimeParams.varianceSensitivity;
        var["CB"]["gMinRayCount"] = mRuntimeParams.minRayCount;
        var["CB"]["gMaxRayCount"] = mRuntimeParams.maxRayCount;

        mpCollectCellInfoPass->execute(pRenderContext, uint3(kTotalSurfelLimit, 1, 1));
    }

    {
        FALCOR_PROFILE(pRenderContext, "Update Pass (Accumulate Cell Info Pass)");

        auto var = mpAccumulateCellInfoPass->getRootVar();

        var["CB"]["gCameraPos"] = mCamPos;

        mpAccumulateCellInfoPass->execute(pRenderContext, uint3(mStaticParams.cellCount, 1, 1));
    }

    {
        FALCOR_PROFILE(pRenderContext, "Update Pass (Update Cell To Surfel buffer Pass)");

        auto var = mpUpdateCellToSurfelBuffer->getRootVar();

        var["CB"]["gCameraPos"] = mCamPos;

        mpUpdateCellToSurfelBuffer->execute(pRenderContext, uint3(kTotalSurfelLimit, 1, 1));
    }

    if (!mLockSurfel)
    {
        {
            FALCOR_PROFILE(pRenderContext, "Surfel RayTrace Pass");

            auto var = mRtPass.pVars->getRootVar();
            var["CB"]["gFrameIndex"] = mFrameIndex;
            var["CB"]["gRayStep"] = mRuntimeParams.rayStep;
            var["CB"]["gMaxStep"] = mRuntimeParams.maxStep;

            mpScene->raytrace(pRenderContext, mRtPass.pProgram.get(), mRtPass.pVars, uint3(kRayBudget, 1, 1));
        }

        if (mFrameIndex <= mMaxFrameIndex)
        {
            FALCOR_PROFILE(pRenderContext, "Surfel Integrate Pass");

            pRenderContext->copyResource(mpSurfelHistory.get(), mpSurfelBuffer.get());
            if (mStaticParams.useIrradianceSharing) pRenderContext->copyResource(mpSurfelDepthHistory.get(), mpSurfelDepthTexture.get());
            auto var = mpSurfelIntegratePass->getRootVar();
            var["CB"]["gShortMeanWindow"] = mRuntimeParams.shortMeanWindow;
            var["CB"]["gCameraPos"] = mCamPos;
            var["CB"]["gVarianceSensitivity"] = mRuntimeParams.varianceSensitivity;

            mpSurfelIntegratePass->execute(pRenderContext, uint3(kTotalSurfelLimit, 1, 1));
        }

        {
            FALCOR_PROFILE(pRenderContext, "Surfel Generation Pass");

            auto var = mpSurfelGenerationPass->getRootVar();

            mpScene->bindShaderDataForRaytracing(pRenderContext, var["gScene"], 0);

            var["CB"]["gResolution"] = mFrameDim;
            var["CB"]["gFOVy"] = mFOVy;
            var["CB"]["gFrameIndex"] = mFrameIndex;
            var["CB"]["gChanceMultiply"] = mRuntimeParams.chanceMultiply;
            var["CB"]["gChancePower"] = mRuntimeParams.chancePower;
            var["CB"]["gPlacementThreshold"] = mRuntimeParams.placementThreshold;
            var["CB"]["gRemovalThreshold"] = mRuntimeParams.removalThreshold;
            var["CB"]["gOverlayMode"] = (uint)mRuntimeParams.overlayMode;
            var["CB"]["gBlendingDelay"] = mRuntimeParams.blendingDelay;
            var["CB"]["gVarianceSensitivity"] = mRuntimeParams.varianceSensitivity;

            pRenderContext->clearUAV(mpOutputTexture->getUAV().get(), float4(0));
            mpSurfelGenerationPass->execute(pRenderContext, uint3(mFrameDim, 1));
        }
    }

    if (mQueryCompact || mQueryShared) {
        FALCOR_PROFILE(pRenderContext, "Pack Query Data");
        auto var = mpPackQueryPass->getRootVar();
        var["gSurfelBuffer"] = mpSurfelBuffer;
        var["gSurfelRecycleInfoBuffer"] = mpSurfelRecycleInfoBuffer;
        var["gQueryBuffer"] = mpQueryBuffer;
        mpPackQueryPass->execute(pRenderContext,uint3(kTotalSurfelLimit,1,1));
    }
    {
        FALCOR_PROFILE(pRenderContext, "Surfel Evaluation Pass");

        auto var = mpSurfelEvaluationPass->getRootVar();

        mpScene->bindShaderDataForRaytracing(pRenderContext, var["gScene"], 0);

        if (mQueryCompact || mQueryShared) var["gQueryBuffer"] = mpQueryBuffer;
        var["CB"]["gQueryMark"] = mQueryMark;
        var["CB"]["gFrameIndex"] = mFrameIndex;
        var["CB"]["gPlacementThreshold"] = mRuntimeParams.placementThreshold;
        var["CB"]["gRemovalThreshold"] = mRuntimeParams.removalThreshold;
        var["CB"]["gBlendingDelay"] = mRuntimeParams.blendingDelay;
        var["CB"]["gOverlayMode"] = (uint)mRuntimeParams.overlayMode;
        var["CB"]["gVarianceSensitivity"] = mRuntimeParams.varianceSensitivity;

        pRenderContext->clearUAV(mpOutputTexture->getUAV().get(), float4(0));
        mpSurfelEvaluationPass->execute(pRenderContext, uint3(mFrameDim, 1));
    }

    {
        FALCOR_PROFILE(pRenderContext, "Read Back");

        pRenderContext->copyResource(mpReadBackBuffer.get(), mpSurfelCounter.get());

        pRenderContext->submit(false);
        pRenderContext->signal(mpFence.get());

        mReadBackValid = true;
    }

    mFrameIndex++;
}

void SurfelGI::renderUI(Gui::Widgets& widget)
{
    widget.text("Frame index");
    widget.text(std::to_string(mFrameIndex), true);

    widget.dummy("#spacer0", {1, 10});

    if (mReadBackValid)
    {
        mpFence->wait();
        const uint validSurfelCount = mpReadBackBuffer->getElement<uint>(0);
        const uint requestedRayCount = mpReadBackBuffer->getElement<uint>(4);
        const uint filledCellCount = mpReadBackBuffer->getElement<uint>(3);

        std::rotate(mSurfelCount.begin(), mSurfelCount.begin() + 1, mSurfelCount.end());
        mSurfelCount[mSurfelCount.size() - 1] = (float)validSurfelCount / kTotalSurfelLimit;

        widget.graph("", plotFunc, mSurfelCount.data(), mSurfelCount.size(), 0, 0, FLT_MAX, 0, 25u);

        widget.text("Presented surfel");
        widget.text(std::to_string(validSurfelCount) + " / " + std::to_string(kTotalSurfelLimit), true);
        widget.text("(" + std::to_string(validSurfelCount * 100.0f / kTotalSurfelLimit) + " %)", true);

        std::rotate(mRayBudget.begin(), mRayBudget.begin() + 1, mRayBudget.end());
        mRayBudget[mRayBudget.size() - 1] = (float)requestedRayCount / kRayBudget;

        widget.graph("", plotFunc, mRayBudget.data(), mRayBudget.size(), 0, 0, FLT_MAX, 0, 25u);

        widget.text("Ray budget");
        widget.text(std::to_string(requestedRayCount) + " / " + std::to_string(kRayBudget), true);
        widget.text("(" + std::to_string(requestedRayCount * 100.0f / kRayBudget) + " %)", true);

        widget.text("Surfel shortage");
        widget.text(std::to_string(mpReadBackBuffer->getElement<int>(2)), true);
        widget.tooltip("Positive if there is enough memory for the new surfel, negative otherwise.");

        widget.text("Miss ray bounce");
        widget.text(std::to_string(mpReadBackBuffer->getElement<uint>(5)), true);
        widget.tooltip("The number of rays that failed to find surfel and move on to the next step.");

        widget.text("Visible distance");
        widget.text(std::to_string(mStaticParams.cellDim * mStaticParams.cellUnit), true);
        widget.tooltip(
            "The maximum distance at which global illumination is drawn. This is affected by the dimensions and size "
            "of the cell."
        );
    }

    widget.dummy("#spacer0", {1, 10});

    {
        bool editted = false;

        widget.text("Adjust render scale");
        widget.tooltip(
            "Adjust render scale, which affects cell unit and camera speed. Try adjusting this value if you think your "
            "scene is too large or too small so the rendering isn't working properly."
        );

        if (widget.var("", mRenderScale, 1e-3f, 1e+3f, 2.f))
        {
            editted = true;
        }
        else if (widget.button("/4"))
        {
            editted = true;
            mRenderScale /= 4;
        }
        else if (widget.button("/2", true))
        {
            editted = true;
            mRenderScale /= 2;
        }
        else if (widget.button("x2", true))
        {
            editted = true;
            mRenderScale *= 2;
        }
        else if (widget.button("x4", true))
        {
            editted = true;
            mRenderScale *= 4;
        }

        if (editted)
        {
            mRenderScale = std::max(1e-3f, std::min(1e+3f, mRenderScale));

            if (mpScene)
                mpScene->setCameraSpeed(mRenderScale);

            mTempStaticParams.cellUnit = 0.05f * mRenderScale;
            resetAndRecompile();
        }
    }

    widget.dummy("#spacer0", {1, 10});

    if (widget.button(!mLockSurfel ? "Lock Surfel" : "Unlock Surfel"))
        mLockSurfel = !mLockSurfel;
    widget.tooltip("Lock / Unlock surfel generation and update operation.");

    if (widget.button("Reset Surfel", true))
        mResetSurfelBuffer = true;
    widget.tooltip("Clears all spawned surfels in the scene.");

    mOptionsChanged |= widget.dropdown("Overlay mode", mRuntimeParams.overlayMode);
    widget.tooltip("Decide what to render.");

    widget.dummy("#spacer0", {1, 10});

    if (auto group = widget.group("Static Params (Needs re-compile)"))
    {
        widget.tooltip("Following parameters needs re-compile. Please press below button after adjusting values.");

        if (widget.button("Recompile"))
            resetAndRecompile();

        if (auto g = group.group("Surfel Generation", true))
        {
            g.slider("Target area size", mTempStaticParams.surfelTargetArea, 200u, 80000u);
            g.var("Cell unit", mTempStaticParams.cellUnit, 0.005f, 100.f);

            if (g.var("Cell dimension", mTempStaticParams.cellDim, 16u, 128u, 2u))
                mTempStaticParams.cellCount =
                    mTempStaticParams.cellDim * mTempStaticParams.cellDim * mTempStaticParams.cellDim;

            g.slider("Per cell surfel limit", mTempStaticParams.perCellSurfelLimit, 2u, 1024u);
        }

        if (auto g = group.group("Ray Tracing", true))
        {
            g.checkbox("Use surfel radiance", mTempStaticParams.useSurfelRadinace);
            g.checkbox("Limit surfel search", mTempStaticParams.limitSurfelSearch);

            if (mTempStaticParams.limitSurfelSearch)
                g.slider("Max surfel for step", mTempStaticParams.maxSurfelForStep, 1u, 100u);

            g.text("Ray guiding disabled: solid-angle PDF validation pending.");
        }

        if (auto g = group.group("Integrate", true))
        {
            g.checkbox("Use surfel depth", mTempStaticParams.useSurfelDepth);
            g.checkbox("Use irradiance sharing", mTempStaticParams.useIrradianceSharing);
        }
    }

    if (auto group = widget.group("Runtime Params"))
    {
        if (auto g = group.group("Surfel Generation", true))
        {
            mOptionsChanged |= g.slider("Chance multiply", mRuntimeParams.chanceMultiply, 0.f, 1.f);
            mOptionsChanged |= g.slider("Chance power", mRuntimeParams.chancePower, 0u, 8u);

            mOptionsChanged |= g.slider("Placement threshold", mRuntimeParams.placementThreshold, 0.f, 10.0f);
            mRuntimeParams.removalThreshold = mRuntimeParams.placementThreshold + mRuntimeParams.thresholdGap;

            mOptionsChanged |= g.slider("Blending delay", mRuntimeParams.blendingDelay, 0u, 2048u);
        }

        if (auto g = group.group("Ray Tracing", true))
        {
            mOptionsChanged |= g.slider("Variance Sensitivity", mRuntimeParams.varianceSensitivity, 0.1f, 100.f);
            mOptionsChanged |= g.slider("Min Ray Count", mRuntimeParams.minRayCount, 4u, mRuntimeParams.maxRayCount);
            mOptionsChanged |= g.slider("Max Ray Count", mRuntimeParams.maxRayCount, std::max(4u, mRuntimeParams.minRayCount), 16u);
            mOptionsChanged |= g.slider("Ray step", mRuntimeParams.rayStep, 0u, mRuntimeParams.maxStep);
            mOptionsChanged |= g.slider("Max step", mRuntimeParams.maxStep, mRuntimeParams.rayStep, 100u);
        }

        if (auto g = group.group("Integrate", true))
        {
            mOptionsChanged |= g.slider("Short mean window", mRuntimeParams.shortMeanWindow, 0.01f, 0.5f);
        }
    }
}

void SurfelGI::setScene(RenderContext* pRenderContext, const ref<Scene>& pScene)
{
    mpScene = pScene;
    if (!mpScene)
        return;

    if (mAutoCellSize) {
        auto bounds = mpScene->getSceneBounds();
        auto cam = mpScene->getCamera()->getPosition();
        auto reach = max(abs(bounds.minPoint - cam), abs(bounds.maxPoint - cam));
        mStaticParams.cellUnit = std::max(0.05f, std::max(reach.x, std::max(reach.y, reach.z)) / 28.f);
        mTempStaticParams = mStaticParams;
    }
    mOptionsChanged = true;
    mFrameIndex = 0;
    mMaxFrameIndex = 1000000;

    mRenderScale = 1.f;
    mIsFrameDimChanged = true;
    mReadBackValid = false;
    mLockSurfel = false;
    mResetSurfelBuffer = false;
    mRecompile = false;
    mSurfelCount = std::vector<float>(1000, 0.f);
    mRayBudget = std::vector<float>(1000, 0.f);

    createPasses();
    createResolutionIndependentResources();
}

bool SurfelGI::onKeyEvent(const KeyboardEvent& keyEvent)
{
    if (keyEvent.key == Input::Key::L)
    {
        mResetSurfelBuffer = true;
        return true;
    }

    return false;
}

void SurfelGI::reflectInput(RenderPassReflection& reflector, uint2 resolution)
{
    reflector.addInput(kPackedHitInfoTextureName, "packed hit info texture")
        .bindFlags(ResourceBindFlags::ShaderResource);
}

void SurfelGI::reflectOutput(RenderPassReflection& reflector, uint2 resolution)
{
    reflector.addOutput(kOutputTextureName, "output texture")
        .format(ResourceFormat::RGBA32Float)
        .bindFlags(ResourceBindFlags::UnorderedAccess);

    reflector.addOutput(kIrradianceMapTextureName, "irradiance map texture")
        .format(ResourceFormat::R32Float)
        .bindFlags(ResourceBindFlags::UnorderedAccess)
        .texture2D(kIrradianceMapRes.x, kIrradianceMapRes.y);

    reflector.addOutput(kSurfelDepthTextureName, "surfel depth texture")
        .format(ResourceFormat::RG32Float)
        .bindFlags(ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource)
        .texture2D(kSurfelDepthTextureRes.x, kSurfelDepthTextureRes.y);
}

void SurfelGI::resetAndRecompile()
{
    mStaticParams = mTempStaticParams;

    // Reset render passes.
    mpSurfelEvaluationPass = nullptr;
    mpPreparePass = nullptr;
    mpCollectCellInfoPass = nullptr;
    mpAccumulateCellInfoPass = nullptr;
    mpUpdateCellToSurfelBuffer = nullptr;
    mpSurfelGenerationPass = nullptr;
    mpSurfelIntegratePass = nullptr;
    mRtPass.pProgram = nullptr;
    mRtPass.pBindingTable = nullptr;
    mRtPass.pVars = nullptr;

    // Reset resources.
    mpSurfelBuffer = nullptr;
    mpSurfelGeometryBuffer = nullptr;
    mpSurfelValidIndexBuffer = nullptr;
    mpSurfelDirtyIndexBuffer = nullptr;
    mpSurfelFreeIndexBuffer = nullptr;
    mpCellInfoBuffer = nullptr;
    mpCellToSurfelBuffer = nullptr;
    mpSurfelRayResultBuffer = nullptr;
    mpSurfelRecycleInfoBuffer = nullptr;
    mpSurfelReservationBuffer = nullptr;
    mpSurfelRefCounter = nullptr;
    mpSurfelCounter = nullptr;
    mpEmptySurfelBuffer = nullptr;
    mpReadBackBuffer = nullptr;

    // #TODO Should reset texture reousrces also?

    // Reset variables.
    mFrameIndex = 0;
    mIsFrameDimChanged = true;
    mReadBackValid = false;
    mLockSurfel = false;

    mRecompile = true;
    mOptionsChanged = true;
}

void SurfelGI::createPasses()
{
    auto defines = mStaticParams.getDefines(*this);
    defines.add(mpScene->getSceneDefines());

    defines.add("QUERY_COMPACT",mQueryCompact ? "1" : "0");
    defines.add("QUERY_SHARED",mQueryShared ? "1" : "0");
    // Evalulation Pass
    mpSurfelEvaluationPass =
        ComputePass::create(mpDevice, (mQueryCompact || mQueryShared) ? "RenderPasses/Surfel/SurfelGI/SurfelEvaluationPass.cs.slang" : "RenderPasses/Surfel/SurfelGI/SurfelEvaluationOriginal.cs.slang", "csMain", defines);

    // Prepare Pass
    mpPreparePass =
        ComputePass::create(mpDevice, "RenderPasses/Surfel/SurfelGI/SurfelPreparePass.cs.slang", "csMain", defines);

    // Update Pass (Collect Cell Info Pass)
    mpCollectCellInfoPass = ComputePass::create(
        mpDevice, "RenderPasses/Surfel/SurfelGI/SurfelUpdatePass.cs.slang", "collectCellInfo", defines
    );

    // Update Pass (Accumulate Cell Info Pass)
    mpAccumulateCellInfoPass = ComputePass::create(
        mpDevice, "RenderPasses/Surfel/SurfelGI/SurfelUpdatePass.cs.slang", "accumulateCellInfo", defines
    );

    // Update Pass (Update Cell To Surfel buffer Pass)
    mpUpdateCellToSurfelBuffer = ComputePass::create(
        mpDevice, "RenderPasses/Surfel/SurfelGI/SurfelUpdatePass.cs.slang", "updateCellToSurfelBuffer", defines
    );

    mpSurfelEvaluationPass->getProgram()->addDefine("QUERY_COMPACT",mQueryCompact ? "1" : "0");
    mpSurfelEvaluationPass->getProgram()->addDefine("QUERY_SHARED",mQueryShared ? "1" : "0");
    mpSurfelEvaluationPass->getProgram()->addDefine("QUERY_MARK",mQueryMark ? "1" : "0");
    mpPackQueryPass = ComputePass::create(mpDevice,"RenderPasses/Surfel/SurfelGI/SurfelEvaluationPass.cs.slang","packQuery",defines);
    // Surfel RayTrace Pass
    {
        ProgramDesc desc;
        desc.addShaderModules(mpScene->getShaderModules());
        desc.addShaderLibrary("RenderPasses/Surfel/SurfelGI/SurfelRayTrace.rt.slang");
        desc.setMaxPayloadSize(72u);
        desc.setMaxAttributeSize(mpScene->getRaytracingMaxAttributeSize());
        desc.setMaxTraceRecursionDepth(2u);

        mRtPass.pBindingTable = RtBindingTable::create(2, 2, mpScene->getGeometryCount());
        mRtPass.pBindingTable->setRayGen(desc.addRayGen("rayGen"));
        mRtPass.pBindingTable->setMiss(0, desc.addMiss("scatterMiss"));
        mRtPass.pBindingTable->setMiss(1, desc.addMiss("shadowMiss"));

        mRtPass.pBindingTable->setHitGroup(
            0,
            mpScene->getGeometryIDs(Scene::GeometryType::TriangleMesh),
            desc.addHitGroup("scatterCloseHit", "scatterAnyHit")
        );

        mRtPass.pBindingTable->setHitGroup(
            1, mpScene->getGeometryIDs(Scene::GeometryType::TriangleMesh), desc.addHitGroup("", "shadowAnyhit")
        );

        mRtPass.pProgram = Program::create(mpDevice, desc, defines);
        mRtPass.pProgram->addDefines(mpSampleGenerator->getDefines());
        mRtPass.pProgram->setTypeConformances(mpScene->getTypeConformances());

        mRtPass.pVars = RtProgramVars::create(mpDevice, mRtPass.pProgram, mRtPass.pBindingTable);
        mpSampleGenerator->bindShaderData(mRtPass.pVars->getRootVar());
    }

    // Surfel Generation Pass
    mpSurfelGenerationPass =
        ComputePass::create(mpDevice, "RenderPasses/Surfel/SurfelGI/SurfelGenerationPass.cs.slang", "csMain", defines);

    // Surfel Integrate Pass
    mpSurfelIntegratePass =
        ComputePass::create(mpDevice, "RenderPasses/Surfel/SurfelGI/SurfelIntegratePass.cs.slang", "csMain", defines);
}

void SurfelGI::createResolutionIndependentResources()
{
    mpQueryBuffer = mpDevice->createStructuredBuffer(48,kTotalSurfelLimit,ResourceBindFlags::UnorderedAccess,MemoryType::DeviceLocal,nullptr,false);
    mpSurfelDepthHistory = mStaticParams.useIrradianceSharing ? mpDevice->createTexture2D(kSurfelDepthTextureRes.x, kSurfelDepthTextureRes.y, ResourceFormat::RG32Float, 1, 1, nullptr, ResourceBindFlags::ShaderResource) : nullptr;
    mpSurfelBuffer = mpDevice->createStructuredBuffer(
        sizeof(Surfel), kTotalSurfelLimit, ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, nullptr, false
    );

    mpSurfelHistory = mpDevice->createStructuredBuffer(sizeof(Surfel), kTotalSurfelLimit, ResourceBindFlags::ShaderResource, MemoryType::DeviceLocal, nullptr, false);
    mpSurfelGeometryBuffer = mpDevice->createStructuredBuffer(
        sizeof(uint4), kTotalSurfelLimit, ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, nullptr, false
    );

    mpSurfelValidIndexBuffer = mpDevice->createStructuredBuffer(
        sizeof(uint), kTotalSurfelLimit, ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, nullptr, false
    );

    mpSurfelDirtyIndexBuffer = mpDevice->createStructuredBuffer(
        sizeof(uint), kTotalSurfelLimit, ResourceBindFlags::ShaderResource, MemoryType::DeviceLocal, nullptr, false
    );

    {
        uint* freeIndexBuffer = new uint[kTotalSurfelLimit];
        std::iota(freeIndexBuffer, freeIndexBuffer + kTotalSurfelLimit, 0);

        mpSurfelFreeIndexBuffer = mpDevice->createStructuredBuffer(
            sizeof(uint),
            kTotalSurfelLimit,
            ResourceBindFlags::UnorderedAccess,
            MemoryType::DeviceLocal,
            freeIndexBuffer,
            false
        );

        delete[] freeIndexBuffer;
    }

    mpCellInfoBuffer = mpDevice->createStructuredBuffer(
        sizeof(CellInfo),
        mStaticParams.cellCount,
        ResourceBindFlags::UnorderedAccess,
        MemoryType::DeviceLocal,
        nullptr,
        false
    );

    mpCellToSurfelBuffer = mpDevice->createStructuredBuffer(
        sizeof(uint),
        kTotalSurfelLimit * 125,
        ResourceBindFlags::UnorderedAccess,
        MemoryType::DeviceLocal,
        nullptr,
        false
    );

    mpSurfelRayResultBuffer = mpDevice->createStructuredBuffer(
        sizeof(SurfelRayResult), kRayBudget, ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, nullptr, false
    );

    mpSurfelRecycleInfoBuffer = mpDevice->createStructuredBuffer(
        sizeof(SurfelRecycleInfo),
        kTotalSurfelLimit,
        ResourceBindFlags::UnorderedAccess,
        MemoryType::DeviceLocal,
        nullptr,
        false
    );

    mpSurfelReservationBuffer = mpDevice->createBuffer(
        sizeof(uint) * mStaticParams.cellCount, ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, nullptr
    );

    mpSurfelRefCounter = mpDevice->createBuffer(
        sizeof(uint) * kTotalSurfelLimit, ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, nullptr
    );

    mpSurfelCounter = mpDevice->createBuffer(
        sizeof(uint) * _countof(kInitialStatus),
        ResourceBindFlags::UnorderedAccess,
        MemoryType::DeviceLocal,
        kInitialStatus
    );

    mpReadBackBuffer = mpDevice->createBuffer(
        sizeof(uint) * _countof(kInitialStatus), ResourceBindFlags::None, MemoryType::ReadBack, nullptr
    );

    mpEmptySurfelBuffer = mpDevice->createStructuredBuffer(
        sizeof(Surfel), kTotalSurfelLimit, ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, nullptr, false
    );
}

void SurfelGI::createResolutionDependentResources() {}

void SurfelGI::bindResources(const RenderData& renderData)
{
    const auto& pPackedHitInfoTexture = renderData.getTexture(kPackedHitInfoTextureName);
    mpOutputTexture = renderData.getTexture(kOutputTextureName);
    mpIrradianceMapTexture = renderData.getTexture(kIrradianceMapTextureName);
    mpSurfelDepthTexture = renderData.getTexture(kSurfelDepthTextureName);

    // Evaluation Pass
    {
        auto var = mpSurfelEvaluationPass->getRootVar();

        var[kSurfelBufferVarName] = mpSurfelBuffer;
        var[kCellInfoBufferVarName] = mpCellInfoBuffer;
        var[kCellToSurfelBufferVarName] = mpCellToSurfelBuffer;
        var[kSurfelRecycleInfoBufferVarName] = mpSurfelRecycleInfoBuffer;

        var[kSurfelRefCounterVarName] = mpSurfelRefCounter;

        var["gPackedHitInfo"] = pPackedHitInfoTexture;
        var["gSurfelDepth"] = mpSurfelDepthTexture;
        var["gOutput"] = mpOutputTexture;

        var["gSurfelDepthSampler"] = mpSurfelDepthSampler;
    }

    // Prepare Pass
    {
        auto var = mpPreparePass->getRootVar();
        var[kSurfelCounterVarName] = mpSurfelCounter;
    }

    // Update Pass (Collect Cell Info Pass)
    {
        auto var = mpCollectCellInfoPass->getRootVar();

        var[kSurfelBufferVarName] = mpSurfelBuffer;
        var[kSurfelGeometryBufferVarName] = mpSurfelGeometryBuffer;
        var[kSurfelDirtyIndexBufferVarName] = mpSurfelDirtyIndexBuffer;
        var[kSurfelValidIndexBufferVarName] = mpSurfelValidIndexBuffer;
        var[kSurfelFreeIndexBufferVarName] = mpSurfelFreeIndexBuffer;
        var[kCellInfoBufferVarName] = mpCellInfoBuffer;
        var[kSurfelRayResultBufferVarName] = mpSurfelRayResultBuffer;
        var[kSurfelRecycleInfoBufferVarName] = mpSurfelRecycleInfoBuffer;

        var[kSurfelRefCounterVarName] = mpSurfelRefCounter;
        var[kSurfelCounterVarName] = mpSurfelCounter;
    }

    // Update Pass (Accumulate Cell Info Pass)
    {
        auto var = mpAccumulateCellInfoPass->getRootVar();

        var[kCellInfoBufferVarName] = mpCellInfoBuffer;
        var[kSurfelCounterVarName] = mpSurfelCounter;

        var[kSurfelReservationBufferVarName] = mpSurfelReservationBuffer;
    }

    // Update Pass (Update Cell To Surfel buffer Pass)
    {
        auto var = mpUpdateCellToSurfelBuffer->getRootVar();

        var[kSurfelBufferVarName] = mpSurfelBuffer;
        var[kSurfelValidIndexBufferVarName] = mpSurfelValidIndexBuffer;
        var[kCellInfoBufferVarName] = mpCellInfoBuffer;
        var[kCellToSurfelBufferVarName] = mpCellToSurfelBuffer;

        var[kSurfelCounterVarName] = mpSurfelCounter;
    }

    // Surfel RayTrace Pass
    {
        auto var = mRtPass.pVars->getRootVar();

        var[kSurfelBufferVarName] = mpSurfelBuffer;
        var[kSurfelGeometryBufferVarName] = mpSurfelGeometryBuffer;
        var[kSurfelFreeIndexBufferVarName] = mpSurfelFreeIndexBuffer;
        var[kSurfelValidIndexBufferVarName] = mpSurfelValidIndexBuffer;
        var[kCellInfoBufferVarName] = mpCellInfoBuffer;
        var[kCellToSurfelBufferVarName] = mpCellToSurfelBuffer;
        var[kSurfelRayResultBufferVarName] = mpSurfelRayResultBuffer;
        var[kSurfelRecycleInfoBufferVarName] = mpSurfelRecycleInfoBuffer;

        var[kSurfelReservationBufferVarName] = mpSurfelReservationBuffer;
        var[kSurfelRefCounterVarName] = mpSurfelRefCounter;
        var[kSurfelCounterVarName] = mpSurfelCounter;

        var["gSurfelDepth"] = mpSurfelDepthTexture;
        var["gIrradianceMap"] = mpIrradianceMapTexture;

        var["gSurfelDepthSampler"] = mpSurfelDepthSampler;
    }

    // Surfel Generation Pass
    {
        auto var = mpSurfelGenerationPass->getRootVar();

        var[kSurfelBufferVarName] = mpSurfelBuffer;
        var[kSurfelGeometryBufferVarName] = mpSurfelGeometryBuffer;
        var[kSurfelFreeIndexBufferVarName] = mpSurfelFreeIndexBuffer;
        var[kSurfelValidIndexBufferVarName] = mpSurfelValidIndexBuffer;
        var[kCellInfoBufferVarName] = mpCellInfoBuffer;
        var[kCellToSurfelBufferVarName] = mpCellToSurfelBuffer;
        var[kSurfelRecycleInfoBufferVarName] = mpSurfelRecycleInfoBuffer;

        var[kSurfelRefCounterVarName] = mpSurfelRefCounter;
        var[kSurfelCounterVarName] = mpSurfelCounter;

        var["gPackedHitInfo"] = pPackedHitInfoTexture;
        var["gSurfelDepth"] = mpSurfelDepthTexture;
        var["gOutput"] = mpOutputTexture;

        var["gSurfelDepthSampler"] = mpSurfelDepthSampler;
    }

    // Surfel Integrate Pass
    {
        auto var = mpSurfelIntegratePass->getRootVar();

        var[kSurfelBufferVarName] = mpSurfelBuffer;
        var[kSurfelValidIndexBufferVarName] = mpSurfelValidIndexBuffer;
        var[kCellInfoBufferVarName] = mpCellInfoBuffer;
        var[kCellToSurfelBufferVarName] = mpCellToSurfelBuffer;
        var[kSurfelRayResultBufferVarName] = mpSurfelRayResultBuffer;

        var[kSurfelCounterVarName] = mpSurfelCounter;

        var["gSurfelDepth"] = mpSurfelDepthHistory;
        var["gSurfelDepthRW"] = mpSurfelDepthTexture;
        var["gSurfelHistory"] = mpSurfelHistory;
        var["gSurfelRecycleInfoBuffer"] = mpSurfelRecycleInfoBuffer;
        var["gIrradianceMap"] = mpIrradianceMapTexture;

        var["gSurfelDepthSampler"] = mpSurfelDepthSampler;
    }
}

Falcor::DefineList SurfelGI::StaticParams::getDefines(const SurfelGI& owner) const
{
    DefineList defines;

    defines.add("SURFEL_TARGET_AREA", std::to_string(surfelTargetArea));
    defines.add("CELL_UNIT", std::to_string(cellUnit));
    defines.add("CELL_DIM", std::to_string(cellDim));
    defines.add("CELL_COUNT", std::to_string(cellCount));
    defines.add("PER_CELL_SURFEL_LIMIT", std::to_string(perCellSurfelLimit));

    if (useSurfelRadinace)
        defines.add("USE_SURFEL_RADIANCE");

    if (limitSurfelSearch)
        defines.add("LIMIT_SURFEL_SEARCH");

    defines.add("MAX_SURFEL_FOR_STEP", std::to_string(maxSurfelForStep));

    if (useRayGuiding)
        defines.add("USE_RAY_GUIDING");

    if (useSurfelDepth)
        defines.add("USE_SURFEL_DEPTH");

    if (useIrradianceSharing)
        defines.add("USE_IRRADIANCE_SHARING");

    return defines;
}

void SurfelGI::setProperties(const Properties& props)
{
    for (const auto& [key, value] : props)
    {
        if (key == "lockSurfel") { mLockSurfel = value; continue; }
        if (key == "queryCompact") mQueryCompact = value;
        else if (key == "queryShared") mQueryShared = value;
        else if (key == "queryMark") { mQueryMark = value; continue; }
        else if (key == "cellSize") { mStaticParams.cellUnit = value; mAutoCellSize = mStaticParams.cellUnit <= 0.f; }
        else if (key == "irradianceSharing") mStaticParams.useIrradianceSharing = value;
        else if (key == "useDepth") mStaticParams.useSurfelDepth = value;
        else if (key == "targetArea") mStaticParams.surfelTargetArea = std::clamp(uint32_t(value), 200u, 80000u);
        else if (key == "maxRays") mRuntimeParams.maxRayCount = std::clamp(uint32_t(value), 4u, 16u);
        else if (key == "raySteps") mRuntimeParams.rayStep = std::clamp(uint32_t(value), 1u, 64u);
        else if (key == "maxSteps") mRuntimeParams.maxStep = std::clamp(uint32_t(value), 1u, 64u);
        else FALCOR_THROW("Unknown SurfelGI property: {}", key);
    }
    if (props.has("lockSurfel") || props.has("queryMark")) return;
    mRuntimeParams.maxStep = std::max(mRuntimeParams.maxStep, mRuntimeParams.rayStep);
    if (mpScene && mAutoCellSize) {
        const auto bounds = mpScene->getSceneBounds();
        const auto cam = mpScene->getCamera()->getPosition();
        const auto reach = max(abs(bounds.minPoint - cam), abs(bounds.maxPoint - cam));
        mStaticParams.cellUnit = std::max(0.05f, std::max(reach.x, std::max(reach.y, reach.z)) / 28.f);
    }
    mTempStaticParams = mStaticParams;
    if (mpScene) { resetAndRecompile(); mOptionsChanged = true; }
}
Properties SurfelGI::getProperties() const
{
    Properties p;
    p["queryCompact"] = mQueryCompact; p["queryShared"] = mQueryShared; p["queryMark"] = mQueryMark;
    p["cellSize"] = mStaticParams.cellUnit;
    p["irradianceSharing"] = mStaticParams.useIrradianceSharing;
    p["useDepth"] = mStaticParams.useSurfelDepth;
    p["targetArea"] = mStaticParams.surfelTargetArea;
    p["maxRays"] = mRuntimeParams.maxRayCount;
    p["raySteps"] = mRuntimeParams.rayStep;
    p["maxSteps"] = mRuntimeParams.maxStep;
    return p;
}

Properties SurfelGI::getStats()
{
    Properties p;
    if (mReadBackValid) {
        mpFence->wait();
        p["surfels"] = mpReadBackBuffer->getElement<uint>(0);
        p["requestedRays"] = mpReadBackBuffer->getElement<uint>(4);
    }
    p["capacity"] = kTotalSurfelLimit; p["rayCapacity"] = kRayBudget;
    p["queryCompact"] = mQueryCompact; p["queryShared"] = mQueryShared; p["queryMark"] = mQueryMark;
    p["cellSize"] = mStaticParams.cellUnit; p["frames"] = mFrameIndex;
    return p;
}
