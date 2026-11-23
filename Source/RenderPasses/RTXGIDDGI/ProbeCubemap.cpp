#include "RTXGIDDGI.h"
#include "Core/API/NativeHandleTraits.h"
#include "Core/API/LowLevelContextData.h"
// Explicit opt-in diagnostics only. Native query results are read after submit/wait;
// pipeline counters are never polled during ordinary rendering or timing runs.
struct ProbeCapturePipelineDiagnostics
{
    ref<Device> device;
    ref<Buffer> readback;
#if FALCOR_HAS_D3D12
    ID3D12QueryHeap* heap = nullptr;
    ~ProbeCapturePipelineDiagnostics()
    {
        if (heap) { device->getRenderContext()->submit(true); heap->Release(); }
    }
#endif
};
Properties RTXGIDDGI::getProbePipelineStats() const
{
    Properties result;
#if FALCOR_HAS_D3D12
    if (mpProbePipelineDiagnostics)
    {
        mpDevice->getRenderContext()->submit(true);
        D3D12_QUERY_DATA_PIPELINE_STATISTICS stats = {};
        mpProbePipelineDiagnostics->readback->getBlob(&stats, 0, sizeof(stats));
        result["IAVertices"] = stats.IAVertices;
        result["IAPrimitives"] = stats.IAPrimitives;
        result["VSInvocations"] = stats.VSInvocations;
        result["GSInvocations"] = stats.GSInvocations;
        result["CInvocations"] = stats.CInvocations;
        result["CPrimitives"] = stats.CPrimitives;
        result["PSInvocations"] = stats.PSInvocations;
    }
#endif
    return result;
}
namespace
{
void setCaptureViewMask(RenderContext* context, uint32_t mask)
{
#if FALCOR_HAS_D3D12
    auto native = context->getLowLevelData()->getCommandBufferNativeHandle().as<ID3D12GraphicsCommandList*>();
    ID3D12GraphicsCommandList1* command = nullptr;
    FALCOR_CHECK(SUCCEEDED(native->QueryInterface(IID_PPV_ARGS(&command))), "View instancing requires ID3D12GraphicsCommandList1.");
    command->SetViewInstanceMask(mask);
    command->Release();
#endif
}
} // namespace
uint32_t RTXGIDDGI::getProbeViewInstancingTier() const
{
#if FALCOR_HAS_D3D12 && FALCOR_NVAPI_AVAILABLE
    if (mpDevice->getType() == Device::Type::D3D12)
    {
        D3D12_FEATURE_DATA_D3D12_OPTIONS3 options = {};
        auto device = mpDevice->getNativeHandle().as<ID3D12Device*>();
        if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS3, &options, sizeof(options))))
            return uint32_t(options.ViewInstancingTier);
    }
#endif
    return 0;
}

void RTXGIDDGI::rasterizeProbes(RenderContext* context, const RenderData& data)
{
    FALCOR_PROFILE(context, "RasterProbeCapture");
    FALCOR_CHECK(!mOptions.validateCapture || mProbeBatchCount <= 32, "Capture validation requires a single batch of at most 32 probes.");
    FALCOR_CHECK(mOptions.probeCaptureDiagnosticMode <= 5, "Invalid capture diagnostic mode.");
    FALCOR_CHECK(mOptions.probeCaptureDiagnosticMode == 0 || (mOptions.captureOnly && mOptions.optimizedProbeCapture && !mOptions.validateCapture),
        "Capture ablation requires captureOnly, optimized capture, and validation disabled.");
#if FALCOR_HAS_D3D12
    ID3D12GraphicsCommandList* queryCommand = nullptr;
    if (mOptions.probeCapturePipelineStats)
    {
        FALCOR_CHECK(mpDevice->getType() == Device::Type::D3D12, "Native pipeline statistics require D3D12.");
        if (!mpProbePipelineDiagnostics)
        {
            auto diag = std::make_shared<ProbeCapturePipelineDiagnostics>();
            diag->device = mpDevice;
            D3D12_QUERY_HEAP_DESC desc = {}; desc.Count = 1; desc.Type = D3D12_QUERY_HEAP_TYPE_PIPELINE_STATISTICS;
            auto nativeDevice = mpDevice->getNativeHandle().as<ID3D12Device*>();
            FALCOR_CHECK(SUCCEEDED(nativeDevice->CreateQueryHeap(&desc, IID_PPV_ARGS(&diag->heap))), "Could not create capture statistics query.");
            diag->readback = mpDevice->createBuffer(sizeof(D3D12_QUERY_DATA_PIPELINE_STATISTICS), ResourceBindFlags::None, MemoryType::ReadBack);
            mpProbePipelineDiagnostics = diag;
        }

    }
#endif
    const uint32_t size = mOptions.probeCubemapSize, layers = 32 * 6;
    if (!mpProbeCaptureHits || mpProbeCaptureHits->getWidth() != size)
    {
        mpProbeCaptureHits = mpDevice->createTexture2D(size, size, ResourceFormat::RGBA32Uint, layers, 1, nullptr,
                                                       ResourceBindFlags::RenderTarget | ResourceBindFlags::ShaderResource |
                                                           ResourceBindFlags::UnorderedAccess);
        mpProbeCaptureDepth =
            mpDevice->createTexture2D(size, size, ResourceFormat::D32Float, layers, 1, nullptr, ResourceBindFlags::DepthStencil);
        mpProbeCaptureFbo = Fbo::create(mpDevice);
        mpProbeCaptureFbo->attachColorTarget(mpProbeCaptureHits, 0);
        mpProbeCaptureFbo->attachDepthStencilTarget(mpProbeCaptureDepth);
    }
    const bool optimized = mOptions.optimizedProbeCapture && mpScene->getMeshVao()->getIndexBuffer();
    const bool multiview = optimized && mOptions.multiviewProbeCapture && getProbeViewInstancingTier() >= 2;
    const bool acrossProbes = multiview && mOptions.multiviewAcrossProbes;
    const bool precompute = optimized && mOptions.precomputeProbePositions;
    const uint32_t diagnosticShader = mOptions.probeCaptureDiagnosticMode == 5 ? 3u : mOptions.probeCaptureDiagnosticMode == 4 ? 2u :
        ((mOptions.probeCaptureDiagnosticMode != 0 || mOptions.probeCaptureDiagnosticRestore) ? 1u : 0u);
    const uint32_t programIndex = (multiview ? (acrossProbes ? 3u : 2u) : uint32_t(optimized)) + diagnosticShader * 4 + (precompute ? 16u : 0u);
    if (!mpProbeCaptureProgram || mProbeCaptureOptimized != optimized || mProbeCaptureMultiview != multiview ||
        mProbeCaptureAcrossProbes != acrossProbes || mProbeCaptureDiagnosticShader != diagnosticShader || mProbeCapturePrecomputed != precompute)
    {
        mProbeCaptureOptimized = optimized;
        mProbeCaptureMultiview = multiview;
        mProbeCaptureAcrossProbes = acrossProbes;
        mProbeCaptureDiagnosticShader = diagnosticShader;
        mProbeCapturePrecomputed = precompute;
        if (!mpProbeCapturePrograms[programIndex])
        {
            ProgramDesc desc;
            desc.addShaderModules(mpScene->getShaderModules());
            desc.addShaderLibrary(mProbeCaptureOptimized ? "RenderPasses/RTXGIDDGI/ProbeCubemapIndirect.3d.slang"
                                                         : "RenderPasses/RTXGIDDGI/ProbeCubemap.3d.slang")
                .vsEntry("vsMain")
                .psEntry("psMain");
            if (!mProbeCaptureOptimized)
                desc.gsEntry("gsMain");
            desc.addTypeConformances(mpScene->getTypeConformances());
            auto defines = mpScene->getSceneDefines();
            defines.add("PROBE_CAPTURE_DIAGNOSTICS", diagnosticShader != 0 ? "1" : "0");
            defines.add("PROBE_CAPTURE_INDEPENDENT_VIEW", diagnosticShader == 3 ? "1" : "0");
            defines.add("PROBE_CAPTURE_NO_VERTEX_POSITION", diagnosticShader == 2 ? "1" : "0");
            defines.add("PROBE_PRECOMPUTED_POSITIONS", precompute ? "1" : "0");
            defines.add("PROBE_MULTIVIEW", multiview ? "1" : "0");
            defines.add("PROBE_MULTIVIEW_ACROSS_PROBES", acrossProbes ? "1" : "0");
            mpProbeCapturePrograms[programIndex] = Program::create(mpDevice, desc, defines);
            mpProbeCaptureVariables[programIndex] = ProgramVars::create(mpDevice, mpProbeCapturePrograms[programIndex].get());
        }
        mpProbeCaptureProgram = mpProbeCapturePrograms[programIndex];
        mpProbeCaptureVars = mpProbeCaptureVariables[programIndex];
        mpProbeCaptureState = GraphicsState::create(mpDevice);
        mpProbeCaptureState->setProgram(mpProbeCaptureProgram);
        DepthStencilState::Desc ds;
        ds.setDepthFunc(ComparisonFunc::GreaterEqual).setDepthWriteMask(true); // Reversed-Z.
        mpProbeCaptureState->setDepthStencilState(DepthStencilState::create(ds));
        RasterizerState::Desc rs;
        rs.setCullMode(RasterizerState::CullMode::None);
        mpProbeCaptureState->setRasterizerState(RasterizerState::create(rs));
    }
    mpProbeCaptureState->setFbo(mpProbeCaptureFbo);
    const uint32_t instances = mpScene->getGeometryInstanceCount(), commands = instances * 192;
    if (mProbeCaptureOptimized && !mpProbeMeshBounds)
    {
        std::vector<float4> bounds(mpScene->getMeshCount() * 2);
        for (uint32_t i = 0; i < mpScene->getMeshCount(); i++)
        {
            const auto& b = mpScene->getMeshBounds(i);
            bounds[i * 2] = float4(b.center(), 0);
            bounds[i * 2 + 1] = float4(b.extent() * .5f, 0);
        }
        mpProbeMeshBounds = mpDevice->createStructuredBuffer(16, bounds.size(), ResourceBindFlags::ShaderResource, MemoryType::DeviceLocal,
                                                             bounds.data(), false);
        // D3D12 SV_InstanceID does not include StartInstanceLocation. Use Falcor's
        // per-instance DRAW_ID attribute, extended to encode the probe face too.
        const auto sourceVao = mpScene->getMeshVao();
        const uint32_t drawSlot = sourceVao->getElementIndexByLocation(3).vbIndex;
        std::vector<uint32_t> ids(commands);
        for (uint32_t i = 0; i < commands; ++i)
            ids[i] = i;
        auto idBuffer =
            mpDevice->createBuffer(ids.size() * sizeof(uint32_t), ResourceBindFlags::Vertex, MemoryType::DeviceLocal, ids.data());
        auto idLayout = VertexBufferLayout::create();
        idLayout->addElement("DRAW_ID", 0, ResourceFormat::R32Uint, 1, 3);
        idLayout->setInputClass(VertexBufferLayout::InputClass::PerInstanceData, 1);
        auto layout = VertexLayout::create();
        Vao::BufferVec buffers;
        for (uint32_t i = 0; i < sourceVao->getVertexBuffersCount(); ++i)
        {
            layout->addBufferLayout(i, i == drawSlot ? idLayout : sourceVao->getVertexLayout()->getBufferLayout(i));
            buffers.push_back(i == drawSlot ? idBuffer : sourceVao->getVertexBuffer(i));
        }
        mpProbeCaptureVao16 =
            Vao::create(sourceVao->getPrimitiveTopology(), layout, buffers, sourceVao->getIndexBuffer(), ResourceFormat::R16Uint);
        mpProbeCaptureVao32 =
            Vao::create(sourceVao->getPrimitiveTopology(), layout, buffers, sourceVao->getIndexBuffer(), ResourceFormat::R32Uint);
        const auto flags = ResourceBindFlags::UnorderedAccess | ResourceBindFlags::IndirectArg;
        mpProbeDraw16 = mpDevice->createBuffer(size_t(commands) * 7 * 20, flags, MemoryType::DeviceLocal);
        mpProbeDraw32 = mpDevice->createBuffer(size_t(commands) * 7 * 20, flags, MemoryType::DeviceLocal);
        mpProbeDrawCounts = mpDevice->createBuffer(14 * 4, flags, MemoryType::DeviceLocal);
        mpProbeViewMasks =
            mpDevice->createStructuredBuffer(4, commands, ResourceBindFlags::UnorderedAccess | ResourceBindFlags::ShaderResource);
        ProgramDesc cull;
        cull.addShaderModules(mpScene->getShaderModules());
        cull.addShaderLibrary("RenderPasses/RTXGIDDGI/ProbeCubemapCull.cs.slang").csEntry("main");
        cull.addTypeConformances(mpScene->getTypeConformances());
        mpProbeCaptureCull = ComputePass::create(mpDevice, cull, mpScene->getSceneDefines());
    }
    auto root = mpProbeCaptureVars->getRootVar();
    if (!precompute) root["DDGIVolumes"] = mpVolume;
    if (optimized && diagnosticShader != 0) root["CaptureDiagnosticCB"]["gDiagnosticMode"] = mOptions.probeCaptureDiagnosticMode;
    if (multiview)
    {
        root["gViewMasks"] = mpProbeViewMasks;
        root[acrossProbes ? "gFalcorViewInstancing3AcrossProbes" : "gFalcorViewInstancing3"]["viewCount"] = 3u;
    }
    if (!precompute) root["gProbeData"] = mpProbeData;
    FALCOR_CHECK(mOptions.probeCaptureTriangleDivisor == 1 || (mOptions.captureOnly && mOptions.probeCaptureDiagnosticMode >= 2),
        "Triangle reduction is only supported in clip-all capture diagnostics.");
#if FALCOR_HAS_D3D12
    if (mOptions.probeCapturePipelineStats)
    {
        queryCommand = context->getLowLevelData()->getCommandBufferNativeHandle().as<ID3D12GraphicsCommandList*>();
        queryCommand->BeginQuery(mpProbePipelineDiagnostics->heap, D3D12_QUERY_TYPE_PIPELINE_STATISTICS, 0);
    }
#endif
    const uint32_t total = mOptions.counts.x * mOptions.counts.y * mOptions.counts.z;
    if (precompute && mProbeBatchCount > 0)
    {
        FALCOR_PROFILE(context, "PrecomputeProbePositions");
        if (!mpPrecomputeProbePositions)
            mpPrecomputeProbePositions = ComputePass::create(mpDevice, "RenderPasses/RTXGIDDGI/PrecomputeProbePositions.cs.slang", "main");
        if (!mpCaptureProbePositions || mCaptureProbePositionCapacity < mProbeBatchCount)
        {
            mCaptureProbePositionCapacity = mProbeBatchCount;
            mpCaptureProbePositions = mpDevice->createStructuredBuffer(sizeof(float4), mCaptureProbePositionCapacity,
                ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess);
        }
        auto positions = mpPrecomputeProbePositions->getRootVar();
        positions["DDGIVolumes"] = mpVolume;
        positions["gProbeData"] = mpProbeData;
        positions["gPositions"] = mpCaptureProbePositions;
        positions["PositionCB"]["gStart"] = mProbeCursor;
        positions["PositionCB"]["gCount"] = mProbeBatchCount;
        positions["PositionCB"]["gTotal"] = total;
        mpPrecomputeProbePositions->execute(context, uint3(mProbeBatchCount, 1, 1));
        // Capture reads this frame's relocated positions before the SDK updates relocation.
        context->resourceBarrier(mpCaptureProbePositions.get(), Resource::State::ShaderResource);
        root["gCaptureProbePositions"] = mpCaptureProbePositions;
    }
    for (uint32_t offset = 0; offset < mProbeBatchCount; offset += 32)
    {
        uint32_t count = std::min(32u, mProbeBatchCount - offset);
        context->clearUAV(mpProbeCaptureHits->getUAV().get(), uint4(0u));
        context->clearDsv(mpProbeCaptureDepth->getDSV().get(), 0.f, 0); // Reversed-Z.
        if (precompute) root["PositionReadCB"]["gPositionOffset"] = offset;
        root["CaptureCB"]["gStart"] = (mProbeCursor + offset) % total;
        root["CaptureCB"]["gCount"] = count;
        root["CaptureCB"]["gTotal"] = total;
        root["CaptureCB"]["gNear"] = 0.0001f;
        root["CaptureCB"]["gFar"] = std::max(length(mGridMax - mGridMin) * 2.f, 1.f);
        if (mProbeCaptureOptimized)
        {
            {
                FALCOR_PROFILE(context, "CullCaptureDraws");
                context->clearUAV(mpProbeDrawCounts->getUAV().get(), uint4(0));
                auto c = mpProbeCaptureCull->getRootVar();
                mpScene->bindShaderData(c["gScene"]);
                c["DDGIVolumes"] = mpVolume;
                c["gProbeData"] = mpProbeData;
                c["gMeshBounds"] = mpProbeMeshBounds;
                c["gArgs16"] = mpProbeDraw16;
                c["gArgs32"] = mpProbeDraw32;
                c["gCounts"] = mpProbeDrawCounts;
                c["gViewMasks"] = mpProbeViewMasks;
                c["CaptureCB"]["gMultiview"] = multiview;
                c["CaptureCB"]["gAcrossProbes"] = acrossProbes;
                c["CaptureCB"]["gTriangleDivisor"] = mOptions.probeCaptureTriangleDivisor;
                c["CaptureCB"]["gStart"] = (mProbeCursor + offset) % total;
                c["CaptureCB"]["gCount"] = count;
                c["CaptureCB"]["gTotal"] = total;
                c["CaptureCB"]["gNear"] = 0.0001f;
                c["CaptureCB"]["gFar"] = std::max(length(mGridMax - mGridMin) * 2.f, 1.f);
                c["CaptureCB"]["gInstances"] = instances;
                mpProbeCaptureCull->execute(context, uint3(commands, 1, 1));
            }
            {
                FALCOR_PROFILE(context, "RasterVisibility");
                context->resourceBarrier(mpProbeDrawCounts.get(), Resource::State::IndirectArg);
                mpScene->bindShaderData(root["gScene"]);
                const uint32_t buckets = multiview ? 7u : 1u;
                for (uint32_t bucket = 0; bucket < buckets; ++bucket)
                {
                    if (multiview)
                        setCaptureViewMask(context, bucket + 1);
                    const uint64_t argumentOffset = uint64_t(bucket) * commands * 20;
                    const uint32_t count16 = multiview ? bucket * 4 : 0;
                    const uint32_t count32 = multiview ? (7 + bucket) * 4 : 4;
                    mpProbeCaptureState->setVao(mpProbeCaptureVao16);
                    context->drawIndexedIndirect(mpProbeCaptureState.get(), mpProbeCaptureVars.get(), commands, mpProbeDraw16.get(),
                                                 argumentOffset, mpProbeDrawCounts.get(), count16);
                    mpProbeCaptureState->setVao(mpProbeCaptureVao32);
                    context->drawIndexedIndirect(mpProbeCaptureState.get(), mpProbeCaptureVars.get(), commands, mpProbeDraw32.get(),
                                                 argumentOffset, mpProbeDrawCounts.get(), count32);
                }
                if (multiview)
                    setCaptureViewMask(context, 7u);
            }
        }
        else
        {
            FALCOR_PROFILE(context, "RasterVisibility");
            mpScene->rasterize(context, mpProbeCaptureState.get(), mpProbeCaptureVars.get(), RasterizerState::CullMode::None);
        }
        if (mOptions.validateCapture)
        {
            FALCOR_PROFILE(context, "ValidateCapture");
            if (!mpProbeCaptureReference || mpProbeCaptureReference->getWidth() != size)
                mpProbeCaptureReference = mpDevice->createTexture2D(size, size, ResourceFormat::RGBA32Uint, layers, 1, nullptr,
                                                                    ResourceBindFlags::ShaderResource);
            if (!mProbeCaptureOptimized)
                context->copyResource(mpProbeCaptureReference.get(), mpProbeCaptureHits.get());
            else
            {
                if (!mpProbeCaptureCompare)
                {
                    ProgramDesc cmp;
                    cmp.addShaderModules(mpScene->getShaderModules());
                    cmp.addShaderLibrary("RenderPasses/RTXGIDDGI/ProbeCubemapCompare.cs.slang").csEntry("main");
                    cmp.addTypeConformances(mpScene->getTypeConformances());
                    mpProbeCaptureCompare = ComputePass::create(mpDevice, cmp, mpScene->getSceneDefines());
                    mpProbeCaptureDifference = mpDevice->createBuffer(32, ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal);
                }
                context->clearUAV(mpProbeCaptureDifference->getUAV().get(), uint4(0));
                auto c = mpProbeCaptureCompare->getRootVar();
                mpScene->bindShaderData(c["gScene"]);
                c["gReference"] = mpProbeCaptureReference;
                c["gCurrent"] = mpProbeCaptureHits;
                c["gDifference"] = mpProbeCaptureDifference;
                c["CompareCB"]["gSize"] = size;
                c["CompareCB"]["gLayers"] = count * 6;
                mpProbeCaptureCompare->execute(context, uint3(size, size, count * 6));
            }
        }
        if (mOptions.probeCaptureDiagnosticRestore)
        {
            FALCOR_CHECK(mOptions.captureOnly && mProbeBatchCount <= 32, "Diagnostic restore requires frozen single-batch capture.");
            if (!mpProbeCaptureReference || mpProbeCaptureReference->getWidth() != size)
                mpProbeCaptureReference = mpDevice->createTexture2D(size,size,ResourceFormat::RGBA32Uint,layers,1,nullptr,ResourceBindFlags::ShaderResource);
            if (mOptions.probeCaptureDiagnosticMode == 0) context->copyResource(mpProbeCaptureReference.get(),mpProbeCaptureHits.get());
            else context->copyResource(mpProbeCaptureHits.get(),mpProbeCaptureReference.get());
        }
        if (mOptions.probeCaptureDiagnosticMode != 0 && !mOptions.probeCaptureDiagnosticRestore) continue;
        mRasterOffset = offset;
        bindRayProgram(mTrace, data);
        {
            FALCOR_PROFILE(context, "CapturedSampleShading");
            mpScene->raytrace(context, mTrace.program.get(), mTrace.vars, uint3(mOptions.rays, count, 1));
        }
    }
    mRasterOffset = 0;
#if FALCOR_HAS_D3D12
    if (queryCommand)
    {
        auto native = context->getLowLevelData()->getCommandBufferNativeHandle().as<ID3D12GraphicsCommandList*>();
        FALCOR_CHECK(native == queryCommand, "Capture statistics query crossed a command-list submission.");
        native->EndQuery(mpProbePipelineDiagnostics->heap, D3D12_QUERY_TYPE_PIPELINE_STATISTICS, 0);
        native->ResolveQueryData(mpProbePipelineDiagnostics->heap, D3D12_QUERY_TYPE_PIPELINE_STATISTICS, 0, 1,
            mpProbePipelineDiagnostics->readback->getNativeHandle().as<ID3D12Resource*>(), 0);
    }
#endif
}
