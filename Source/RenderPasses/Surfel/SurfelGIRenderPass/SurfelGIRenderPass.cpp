#include "SurfelGIRenderPass.h"
#include "RenderGraph/RenderPassStandardFlags.h"

SurfelGIRenderPass::SurfelGIRenderPass(ref<Device> pDevice, const Properties& props) : RenderPass(pDevice)
{
    // Check device feature support.
    mpDevice = pDevice;
    if (!mpDevice->isShaderModelSupported(ShaderModel::SM6_5))
        FALCOR_THROW("SceneDebugger requires Shader Model 6.5 support.");

    mpState = ComputeState::create(mpDevice);

    mpSampleGenerator = SampleGenerator::create(mpDevice, SAMPLE_GENERATOR_DEFAULT);
    FALCOR_ASSERT(mpSampleGenerator);

    mFrameIndex = 0;
}

RenderPassReflection SurfelGIRenderPass::reflect(const CompileData& compileData)
{
    RenderPassReflection reflector;

    // Input
    reflector.addInput("packedHitInfo", "packed hit info texture")
        .bindFlags(ResourceBindFlags::ShaderResource);

    reflector.addInput("indirectLighting", "indirect lighting texture")
        .format(ResourceFormat::RGBA32Float)
        .bindFlags(ResourceBindFlags::ShaderResource);

    // Output
    reflector.addOutput("output", "output texture")
        .format(ResourceFormat::RGBA32Float)
        .bindFlags(ResourceBindFlags::UnorderedAccess);

    return reflector;
}

void SurfelGIRenderPass::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    if (!mpScene) return;
    if (mOptionsChanged) {
        auto& dict = renderData.getDictionary();
        dict[kRenderPassRefreshFlags] = dict.getValue(kRenderPassRefreshFlags, RenderPassRefreshFlags::None) | RenderPassRefreshFlags::RenderOptionsChanged;
        mOptionsChanged = false;
    }
    const auto& pPackedHitInfo = renderData.getTexture("packedHitInfo");
    const auto& pIndirectLighting = renderData.getTexture("indirectLighting");
    const auto& pOutput = renderData.getTexture("output");

    FALCOR_ASSERT(pPackedHitInfo && pIndirectLighting && pOutput);

    if (mpProgram)
    {
        auto var = mpVars->getRootVar();
        mpScene->bindShaderDataForRaytracing(pRenderContext, var["gScene"], 0);

        var["CB"]["gResolution"] = renderData.getDefaultTextureDims();
        var["CB"]["gFrameIndex"] = mFrameIndex;
        var["CB"]["gRenderDirectLighting"] = mRenderDirectLighting;
        var["CB"]["gRenderIndirectLighting"] = mRenderIndirectLighting;

        var["gPackedHitInfo"] = pPackedHitInfo;
        var["gIndirectLighting"] = pIndirectLighting;
        var["gOutput"] = pOutput;

        pRenderContext->clearUAV(pOutput->getUAV().get(), float4(0));

        uint3 threadGroupSize = mpProgram->getReflector()->getThreadGroupSize();
        uint3 groups = div_round_up(uint3(renderData.getDefaultTextureDims(), 1), threadGroupSize);
        pRenderContext->dispatch(mpState.get(), mpVars.get(), groups);
    }

    mFrameIndex++;
}

void SurfelGIRenderPass::renderUI(Gui::Widgets& widget)
{
    mOptionsChanged |= widget.checkbox("Direct Lighting", mRenderDirectLighting);
    mOptionsChanged |= widget.checkbox("Indirect Lighting", mRenderIndirectLighting);
}

void SurfelGIRenderPass::setScene(RenderContext* pRenderContext, const ref<Scene>& pScene)
{
    mpScene = pScene;
    mOptionsChanged = true;
    mRenderDirectLighting = true;
    mRenderIndirectLighting = true;

    if (mpScene)
    {
        ProgramDesc desc;
        desc.addShaderModules(mpScene->getShaderModules());
        desc.addShaderLibrary("RenderPasses/Surfel/SurfelGIRenderPass/SurfelGIRenderPass.cs.slang")
            .csEntry("csMain");
        desc.addTypeConformances(mpScene->getTypeConformances());

        mpProgram = Program::create(mpDevice, desc, mpScene->getSceneDefines());
        mpProgram->addDefines(mpSampleGenerator->getDefines());

        mpState->setProgram(mpProgram);

        mpVars = ProgramVars::create(mpDevice, mpProgram.get());
        mpSampleGenerator->bindShaderData(mpVars->getRootVar());
    }
}
