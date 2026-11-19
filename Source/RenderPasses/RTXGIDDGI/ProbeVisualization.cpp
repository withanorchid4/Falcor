#include "RTXGIDDGI.h"

// A shared unit-sphere procedural BLAS and one GPU-positioned TLAS instance per
// probe. Independent of the scene's acceleration structures and GI estimators.
void RTXGIDDGI::drawProbeVisualization(RenderContext* context, const RenderData& data)
{
    if (!mOptions.showProbes) return;
    FALCOR_PROFILE(context, "ProbeVisualization");
    const char* shader = "RenderPasses/RTXGIDDGI/ProbeVisualization.cs.slang";
    if (!mpProbeVisUpdate)
    {
        ProgramDesc update;
        update.addShaderLibrary(shader).csEntry("updateInstances").setShaderModel(ShaderModel::SM6_5);
        mpProbeVisUpdate = ComputePass::create(mpDevice, update);
        ProgramDesc draw;
        draw.addShaderLibrary(shader).csEntry("drawProbes").setShaderModel(ShaderModel::SM6_5);
        mpProbeVisDraw = ComputePass::create(mpDevice, draw);
    }
    const auto allocateAS = [&](const RtAccelerationStructureBuildInputs& inputs,
        ref<Buffer>& buffer, ref<Buffer>& scratch, ref<RtAccelerationStructure>& as)
    {
        auto sizes = RtAccelerationStructure::getPrebuildInfo(mpDevice.get(), inputs);
        buffer = mpDevice->createBuffer(sizes.resultDataMaxSize, ResourceBindFlags::AccelerationStructure, MemoryType::DeviceLocal);
        scratch = mpDevice->createBuffer(sizes.scratchDataSize, ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal);
        RtAccelerationStructure::Desc desc;
        desc.setKind(inputs.kind).setBuffer(buffer, 0, sizes.resultDataMaxSize);
        as = RtAccelerationStructure::create(mpDevice, desc);
    };
    if (!mpProbeVisBlas)
    {
        const float bounds[] = {-1.f, -1.f, -1.f, 1.f, 1.f, 1.f};
        mpProbeVisBounds = mpDevice->createBuffer(sizeof(bounds), ResourceBindFlags::ShaderResource, MemoryType::DeviceLocal, bounds);
        RtGeometryDesc geometry = {};
        geometry.type = RtGeometryType::ProcedurePrimitives;
        geometry.flags = RtGeometryFlags::Opaque;
        geometry.content.proceduralAABBs = {1, mpProbeVisBounds->getGpuAddress(), sizeof(bounds)};
        RtAccelerationStructureBuildInputs inputs = {};
        inputs.kind = RtAccelerationStructureKind::BottomLevel;
        inputs.flags = RtAccelerationStructureBuildFlags::PreferFastTrace;
        inputs.descCount = 1;
        inputs.geometryDescs = &geometry;
        allocateAS(inputs, mpProbeVisBlasBuffer, mpProbeVisBlasScratch, mpProbeVisBlas);
        context->resourceBarrier(mpProbeVisBounds.get(), Resource::State::NonPixelShader);
        RtAccelerationStructure::BuildDesc build = {};
        build.inputs = inputs; build.dest = mpProbeVisBlas.get(); build.scratchData = mpProbeVisBlasScratch->getGpuAddress();
        context->buildAccelerationStructure(build, 0, nullptr);
        context->uavBarrier(mpProbeVisBlasBuffer.get());
    }
    const uint32_t count = mOptions.counts.x * mOptions.counts.y * mOptions.counts.z;
    RtAccelerationStructureBuildInputs inputs = {};
    inputs.kind = RtAccelerationStructureKind::TopLevel;
    inputs.flags = RtAccelerationStructureBuildFlags::PreferFastTrace;
    inputs.descCount = count;
    if (count != mProbeVisCount)
    {
        static_assert(sizeof(RtInstanceDesc) == 64);
        std::vector<RtInstanceDesc> instances(count);
        for (uint32_t i = 0; i < count; ++i)
        {
            instances[i].transform[0][0] = instances[i].transform[1][1] = instances[i].transform[2][2] = 1.f;
            instances[i].instanceID = i;
            instances[i].instanceMask = 0xff;
            instances[i].accelerationStructure = mpProbeVisBlas->getGpuAddress();
        }
        mpProbeVisInstances = mpDevice->createBuffer(count * sizeof(RtInstanceDesc),
            ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess, MemoryType::DeviceLocal, instances.data());
        inputs.instanceDescs = mpProbeVisInstances->getGpuAddress();
        allocateAS(inputs, mpProbeVisTlasBuffer, mpProbeVisTlasScratch, mpProbeVisTlas);
        mProbeVisCount = count;
    }
    const float radius = std::min(mSpacing.x, std::min(mSpacing.y, mSpacing.z)) * .08f;
    {
        FALCOR_PROFILE(context, "UpdateTLAS");
        auto root = mpProbeVisUpdate->getRootVar();
        root["DDGIVolumes"] = mpVolume;
        root["gProbeData"] = mpProbeData;
        root["gInstances"] = mpProbeVisInstances;
        root["VisCB"]["gCount"] = count;
        root["VisCB"]["gRadius"] = radius;
        mpProbeVisUpdate->execute(context, uint3(count, 1, 1));
        context->uavBarrier(mpProbeVisInstances.get());
        context->resourceBarrier(mpProbeVisInstances.get(), Resource::State::NonPixelShader);
        context->uavBarrier(mpProbeVisTlasBuffer.get());
        context->uavBarrier(mpProbeVisTlasScratch.get());
        inputs.instanceDescs = mpProbeVisInstances->getGpuAddress();
        RtAccelerationStructure::BuildDesc build = {};
        build.inputs = inputs; build.dest = mpProbeVisTlas.get(); build.scratchData = mpProbeVisTlasScratch->getGpuAddress();
        context->buildAccelerationStructure(build, 0, nullptr);
        context->uavBarrier(mpProbeVisTlasBuffer.get());
    }
    {
        FALCOR_PROFILE(context, "Draw");
        auto root = mpProbeVisDraw->getRootVar();
        root["gProbeTLAS"].setAccelerationStructure(mpProbeVisTlas);
        root["DDGIVolumes"] = mpVolume;
        root["gProbeData"] = mpProbeData;
        root["gSurfaceDistance"] = mpWrcDebugDepth;
        root["gViewW"] = data.getTexture("viewW");
        root["gColor"] = data.getTexture("color");
        auto direct = data.getTexture("unfilteredColor");
        root["gDirect"] = direct ? direct : data.getTexture("color");
        auto cb = root["VisCB"];
        const auto& camera = mpScene->getCamera()->getData();
        cb["gFrameDim"] = data.getDefaultTextureDims();
        cb["gOrigin"] = camera.posW;
        cb["gJitter"] = float2(-camera.jitterX, camera.jitterY);
        cb["gCameraU"] = camera.cameraU; cb["gCameraV"] = camera.cameraV; cb["gCameraW"] = camera.cameraW;
        cb["gHasView"] = bool(data.getTexture("viewW")); cb["gHasDirect"] = bool(direct);
        context->uavBarrier(data.getTexture("color").get());
        if (direct) context->uavBarrier(direct.get());
        mpProbeVisDraw->execute(context, uint3(data.getDefaultTextureDims(), 1));
    }
}
