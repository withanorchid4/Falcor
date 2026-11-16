#include "RTXGIConfig.slang"

// The host specializes radiance/distance, tile dimensions, and ray count.
#define RTXGI_DDGI_BLEND_SHARED_MEMORY 1
#define RTXGI_DDGI_BLEND_SCROLL_SHARED_MEMORY 0

#include "RTXGI/rtxgi-sdk/shaders/ddgi/ProbeBlendingCS.hlsl"
