#include "DDGIReconstruct.h"

DDGIReconstruct::DDGIReconstruct(ref<Device> device, const Properties& props) : RenderPass(device)
{
    for (const auto& [key, value] : props)
    {
        if (key == "prepare") mPrepare = value;
        else FALCOR_THROW("Unknown DDGIReconstruct property '{}'.", key);
    }
    mpPass = ComputePass::create(mpDevice, "RenderPasses/RTXGIDDGI/DDGIReconstruct.cs.slang", mPrepare ? "prepare" : "resolve");
}
Properties DDGIReconstruct::getProperties() const { Properties p; p["prepare"] = mPrepare; return p; }
RenderPassReflection DDGIReconstruct::reflect(const CompileData& data)
{
    RenderPassReflection r;
    r.addInput("depth", "Full-resolution linear depth");
    if (mPrepare)
    {
        r.addInput("normalRoughness", "Full-resolution NRD normal roughness material ID");
        r.addInput("motion", "Full-resolution world motion");
        const uint2 size = max(data.defaultTexDims / uint2(2), uint2(1));
        r.addOutput("halfDepth", "Decimated depth").format(ResourceFormat::RG32Float).texture2D(size.x,size.y);
        r.addOutput("halfNormalRoughness", "Decimated NRD guide").format(ResourceFormat::RGBA16Float).texture2D(size.x,size.y);
        r.addOutput("halfMotion", "Decimated world motion").format(ResourceFormat::RGBA32Float).texture2D(size.x,size.y);
    }
    else
    {
        for (const char* name : {"normal", "diffuse", "specular", "diffuseReflectance", "specularReflectance", "direct"}) r.addInput(name,name);
        r.addOutput("color", "Full-resolution reconstructed lighting").format(ResourceFormat::RGBA32Float);
    }
    return r;
}
void DDGIReconstruct::execute(RenderContext* context, const RenderData& data)
{
    auto root=mpPass->getRootVar();
    auto bind=[&](const char* name) { root[name]=data.getTexture(name); };
    bind("depth");
    if (mPrepare)
    {
        for (const char* name : {"normalRoughness", "motion", "halfDepth", "halfNormalRoughness", "halfMotion"}) bind(name);
        auto output=data.getTexture("halfDepth");
        mpPass->execute(context,output->getWidth(),output->getHeight());
    }
    else
    {
        for (const char* name : {"normal", "diffuse", "specular", "diffuseReflectance", "specularReflectance", "direct", "color"}) bind(name);
        auto output=data.getTexture("color");
        mpPass->execute(context,output->getWidth(),output->getHeight());
    }
}
