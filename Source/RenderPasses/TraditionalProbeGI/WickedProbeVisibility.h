#pragma once
#include "Falcor.h"
#include "Utils/Properties.h"
#include "Core/Pass/ComputePass.h"
#include <functional>

// Owns only the optional static Wicked visibility data. Never modifies SH or legacy moments.
class WickedProbeVisibility
{
public:
    explicit WickedProbeVisibility(Falcor::ref<Falcor::Device> device);
    void configure(const Falcor::Properties& props);
    void setup(const std::string& sceneIdentity, Falcor::uint3 counts, Falcor::float3 lo, Falcor::float3 hi,
        const std::filesystem::path& baseCache);
    void invalidate();
    void start();
    bool load();
    void step(Falcor::RenderContext* ctx, const std::function<void(uint32_t, uint32_t)>& trace);
    void save(Falcor::RenderContext* ctx);
    uint32_t resolution = 14;
    uint32_t rays = 2048, completed = 0;
    float exponent = 64.f;
    float normalBias = 0.001f, smoothBackface = 0.01f;
    bool ready = false, baking = false;
    float maxDistance = 1.f;
    Falcor::uint2 atlasSize = {1, 1};
    std::string status = "Load/bake SH first, then bake Wicked visibility.";
    std::filesystem::path configuredCache, cacheFile;
    Falcor::ref<Falcor::Texture> moments;
    Falcor::ref<Falcor::Buffer> rayBuffer;
    Falcor::ref<Falcor::Sampler> sampler;
private:
    Falcor::ref<Falcor::Device> mpDevice;
    Falcor::ref<Falcor::Texture> mpAccumulation;
    Falcor::ref<Falcor::ComputePass> mpBlend, mpFinalize;
    uint32_t mProbeCount = 0;
    std::string mKey;
};
