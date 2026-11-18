#pragma once
#include "Falcor.h"
#include "RenderGraph/RenderPass.h"
#include "Core/Pass/ComputePass.h"
using namespace Falcor;

class DDGIReconstruct : public RenderPass
{
public:
    FALCOR_PLUGIN_CLASS(DDGIReconstruct, "DDGIReconstruct", "Half-resolution DDGI guides and bilateral reconstruction.");
    static ref<DDGIReconstruct> create(ref<Device> device, const Properties& props) { return make_ref<DDGIReconstruct>(device, props); }
    DDGIReconstruct(ref<Device> device, const Properties& props);
    Properties getProperties() const override;
    RenderPassReflection reflect(const CompileData& data) override;
    void execute(RenderContext* context, const RenderData& data) override;
private:
    bool mPrepare = false;
    ref<ComputePass> mpPass;
};
