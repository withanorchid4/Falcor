#include "WickedProbeVisibility.h"
#include <fstream>
#include <iomanip>
#include <sstream>
#include <locale>
#include <cmath>
#include <cstring>
#include <limits>
#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
using namespace Falcor;
namespace
{
uint64_t checksum(const void* data, size_t size)
{
    uint64_t h = 14695981039346656037ull;
    auto p = static_cast<const uint8_t*>(data);
    for (size_t i = 0; i < size; ++i) { h ^= p[i]; h *= 1099511628211ull; }
    return h;
}
}
WickedProbeVisibility::WickedProbeVisibility(ref<Device> device) : mpDevice(device)
{
    float2 dummy(1);
    moments = device->createTexture2D(1, 1, ResourceFormat::RG32Float, 1, 1, &dummy, ResourceBindFlags::ShaderResource);
    rayBuffer = device->createStructuredBuffer(sizeof(float4), 1,
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess);
    Sampler::Desc desc;
    desc.setFilterMode(TextureFilteringMode::Linear, TextureFilteringMode::Linear, TextureFilteringMode::Point);
    desc.setAddressingMode(TextureAddressingMode::Clamp, TextureAddressingMode::Clamp, TextureAddressingMode::Clamp);
    sampler = device->createSampler(desc);
}
void WickedProbeVisibility::configure(const Properties& props)
{
    uint32_t nextRays = rays, nextResolution = resolution;
    float nextExponent = exponent, bias = normalBias, backface = smoothBackface;
    auto file = configuredCache;
    for (const auto& [key, value] : props)
    {
        if (key == "wickedResolution") nextResolution = value;
        else if (key == "wickedRaysPerProbe") nextRays = value;
        else if (key == "wickedExponent") nextExponent = value;
        else if (key == "wickedNormalBias") bias = value;
        else if (key == "wickedSmoothBackface") backface = value;
        else if (key == "wickedCacheFile") file = value.operator std::filesystem::path();
        else FALCOR_THROW("Unknown Wicked setting '{}'", key);
    }
    FALCOR_CHECK(nextResolution >= 4 && nextResolution <= 128, "Wicked resolution must be 4..128.");
    FALCOR_CHECK(nextRays >= 512 && nextRays <= 262144, "Wicked rays must be 512..262144.");
    FALCOR_CHECK(std::isfinite(nextExponent) && nextExponent >= 1.f && nextExponent <= 65536.f, "Wicked exponent must be 1..65536.");
    FALCOR_CHECK(std::isfinite(bias) && bias >= 0 && bias <= 1 && std::isfinite(backface) && backface >= 0 && backface <= 1,
        "Invalid Wicked bias/backface blend.");
    if (nextRays != rays || nextResolution != resolution || nextExponent != exponent || file != configuredCache) invalidate();
    exponent = nextExponent; resolution = nextResolution; rays = nextRays; normalBias = bias; smoothBackface = backface; configuredCache = file;
}
void WickedProbeVisibility::invalidate()
{
    ready = baking = false; completed = 0; mKey.clear();
    mpAccumulation = nullptr;
    status = "Wicked visibility needs Bake or Load matching cache.";
}
void WickedProbeVisibility::setup(const std::string& scene, uint3 counts, float3 lo, float3 hi,
    const std::filesystem::path& baseCache)
{
    std::ostringstream key;
    key.imbue(std::locale::classic()); key << std::setprecision(std::numeric_limits<float>::max_digits10);
    key << "WICKED_STATIC_1 df75fbd1 " << resolution << ' ' << exponent << " 0.0001 0.9 0.01 1.5 opaque fibonacci"
        << (rays > 65536 ? "-u32" : "") << " float32\n" << scene << '\n'
        << counts.x << ' ' << counts.y << ' ' << counts.z << ' ' << lo.x << ' ' << lo.y << ' ' << lo.z << ' '
        << hi.x << ' ' << hi.y << ' ' << hi.z << ' ' << rays;
    if (key.str() != mKey)
    {
        invalidate(); mKey = key.str();
        mProbeCount = counts.x * counts.y * counts.z;
        const uint32_t columns = uint32_t(std::ceil(std::sqrt(double(mProbeCount))));
        atlasSize = uint2(columns, (mProbeCount + columns - 1) / columns) * (resolution + 2);
        float3 spacing = (hi - lo) / float3(counts - uint3(1));
        maxDistance = 1.5f * std::max({spacing.x, spacing.y, spacing.z});
        // The parent reports invalid editable bounds; avoid breaking the Current UI while editing them.
        if (!std::isfinite(maxDistance) || maxDistance <= 0) maxDistance = 1.f;
    }
    cacheFile = configuredCache.empty() ? std::filesystem::path(baseCache.string() + (resolution == 14 ? ".wicked-" : ".wicked-r" + std::to_string(resolution) + "-") + std::to_string(rays) + (exponent == 64.f ? "" : fmt::format("-p{}", exponent)) + ".wdist") : configuredCache;
}
void WickedProbeVisibility::start()
{
    FALCOR_CHECK(!mKey.empty() && mProbeCount, "Wicked grid is not initialized.");
    std::vector<float4> zero(size_t(atlasSize.x) * atlasSize.y, float4(0));
    mpAccumulation = mpDevice->createTexture2D(atlasSize.x, atlasSize.y, ResourceFormat::RGBA32Float, 1, 1, zero.data(),
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess);
    rayBuffer = mpDevice->createStructuredBuffer(sizeof(float4), mProbeCount * 16,
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess);
    completed = 0; ready = false; baking = true; status = "Baking Wicked distance moments (SH unchanged).";
}
void WickedProbeVisibility::step(RenderContext* ctx, const std::function<void(uint32_t, uint32_t)>& trace)
{
    if (!baking) return;
    const uint32_t batch = std::min(16u, rays - completed);
    trace(completed, batch);
    ctx->uavBarrier(rayBuffer.get());
    if (!mpBlend) mpBlend = ComputePass::create(mpDevice, "RenderPasses/TraditionalProbeGI/WickedProbeBlend.cs.slang", "blend");
    auto v = mpBlend->getRootVar();
    v["gRays"] = rayBuffer; v["gAccumulation"] = mpAccumulation;
    v["WickedBlendCB"]["gResolution"] = resolution;
    v["WickedBlendCB"]["gProbeCount"] = mProbeCount;
    v["WickedBlendCB"]["gColumns"] = atlasSize.x / (resolution + 2);
    v["WickedBlendCB"]["gBatch"] = batch;
    v["WickedBlendCB"]["gExponent"] = exponent;
    const auto dispatch = [](uint32_t count) { return uint3(std::min(count, 65536u), (count + 65535u) / 65536u, 1); };
    mpBlend->execute(ctx, dispatch(mProbeCount * resolution * resolution));
    ctx->uavBarrier(mpAccumulation.get());
    completed += batch;
    if (completed != rays) return;
    moments = mpDevice->createTexture2D(atlasSize.x, atlasSize.y, ResourceFormat::RG32Float, 1, 1, nullptr,
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess);
    ctx->clearTexture(moments.get(), float4(maxDistance, maxDistance * maxDistance, 0, 0));
    if (!mpFinalize) mpFinalize = ComputePass::create(mpDevice, "RenderPasses/TraditionalProbeGI/WickedProbeBlend.cs.slang", "finalize");
    auto f = mpFinalize->getRootVar();
    f["gAccumulation"] = mpAccumulation; f["gFinal"] = moments;
    f["WickedBlendCB"]["gResolution"] = resolution;
    f["WickedBlendCB"]["gProbeCount"] = mProbeCount;
    f["WickedBlendCB"]["gColumns"] = atlasSize.x / (resolution + 2);
    f["WickedBlendCB"]["gMaxDistance"] = maxDistance;
    mpFinalize->execute(ctx, dispatch(mProbeCount * (resolution + 2) * (resolution + 2)));
    ctx->uavBarrier(moments.get());
    baking = false;
    save(ctx); // validate before declaring it usable
    ready = true; status = "Wicked ready; separate distance cache saved.";
    mpAccumulation = nullptr;
    rayBuffer = mpDevice->createStructuredBuffer(sizeof(float4), 1,
        ResourceBindFlags::ShaderResource | ResourceBindFlags::UnorderedAccess);
    mpBlend = nullptr; mpFinalize = nullptr; // release shader-var references to scratch resources
}
void WickedProbeVisibility::save(RenderContext* ctx)
{
    auto bytes = ctx->readTextureSubresource(moments.get(), 0);
    auto values = reinterpret_cast<const float2*>(bytes.data());
    for (size_t i = 0; i < size_t(atlasSize.x) * atlasSize.y; ++i)
    {
        float2 v = values[i];
        FALCOR_CHECK(std::isfinite(v.x) && std::isfinite(v.y) && v.x >= 0 && v.x <= maxDistance * 1.0001f &&
            v.y >= 0 && v.y <= maxDistance * maxDistance * 1.0001f && v.y + 1e-4f >= v.x * v.x,
            "Invalid Wicked distance moments at {}", i);
    }
    if (!cacheFile.parent_path().empty()) std::filesystem::create_directories(cacheFile.parent_path());
    auto tmp = std::filesystem::path(cacheFile.string() + ".tmp");
    std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
    const uint64_t header[] = {0x31545349444b4357ull, mKey.size(), bytes.size(), checksum(bytes.data(), bytes.size())};
    out.write(reinterpret_cast<const char*>(header), sizeof(header));
    out.write(mKey.data(), mKey.size()); out.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    out.close(); FALCOR_CHECK(bool(out), "Cannot write Wicked cache {}", tmp.string());
#if defined(_WIN32)
    FALCOR_CHECK(MoveFileExW(tmp.c_str(), cacheFile.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH), "Cannot replace Wicked cache.");
#else
    std::filesystem::rename(tmp, cacheFile);
#endif
}
bool WickedProbeVisibility::load()
{
    try
    {
        std::ifstream in(cacheFile, std::ios::binary);
        uint64_t header[4] = {};
        in.read(reinterpret_cast<char*>(header), sizeof(header));
        FALCOR_CHECK(in && header[0] == 0x31545349444b4357ull && header[1] == mKey.size() &&
            header[2] == size_t(atlasSize.x) * atlasSize.y * sizeof(float2), "Missing/mismatched Wicked cache header.");
        std::string key(header[1], '\0'); in.read(key.data(), key.size());
        FALCOR_CHECK(key == mKey, "Wicked cache scene/grid/settings mismatch.");
        std::vector<float2> data(header[2] / sizeof(float2));
        in.read(reinterpret_cast<char*>(data.data()), header[2]);
        FALCOR_CHECK(in && in.peek() == std::char_traits<char>::eof() && checksum(data.data(), header[2]) == header[3],
            "Truncated/corrupt Wicked cache.");
        for (auto v : data) FALCOR_CHECK(std::isfinite(v.x) && std::isfinite(v.y) && v.x >= 0 && v.x <= maxDistance * 1.0001f &&
            v.y >= 0 && v.y <= maxDistance * maxDistance * 1.0001f && v.y + 1e-4f >= v.x * v.x, "Invalid Wicked cached moments.");
        moments = mpDevice->createTexture2D(atlasSize.x, atlasSize.y, ResourceFormat::RG32Float, 1, 1, data.data(), ResourceBindFlags::ShaderResource);
        ready = true; baking = false; completed = rays; mpAccumulation = nullptr;
        status = "Wicked matching distance cache loaded."; return true;
    }
    catch (const std::exception& e) { status = std::string("Wicked cache not loaded: ") + e.what(); return false; }
}
