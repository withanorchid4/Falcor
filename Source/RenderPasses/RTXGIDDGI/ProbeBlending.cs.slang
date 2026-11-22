#include "RTXGIConfig.slang"

#define RTXGI_DDGI_BLEND_SHARED_MEMORY 1
#define RTXGI_DDGI_BLEND_SCROLL_SHARED_MEMORY 0

// Generated SDK adaptation: skip unselected probes before any shared-memory barrier.
#include "RTXGI/rtxgi-sdk/shaders/ddgi/BatchProbeBlendingCS.hlsl"
