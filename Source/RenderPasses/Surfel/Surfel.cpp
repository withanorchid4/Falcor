#include "RenderGraph/RenderPass.h"
#include "SurfelGIRenderPass/SurfelGIRenderPass.h"
#include "SurfelGI/SurfelGI.h"

extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry)
{
    registry.registerClass<RenderPass, SurfelGIRenderPass>();
    registry.registerClass<RenderPass, SurfelGI>();
    ScriptBindings::registerBinding([](pybind11::module& m) {
        pybind11::class_<SurfelGI, RenderPass, ref<SurfelGI>> p(m, "SurfelGI");
        p.def("reset", &SurfelGI::reset);
        p.def_property_readonly("stats", [](SurfelGI& s) { return s.getStats().toPython(); });
    });
}
