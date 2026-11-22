#define SHARC_UPDATE 0
#define SHARC_QUERY 0
#include "SharcCache.slang"
[numthreads(256,1,1)]
void resolve(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= gSharcSize) return;
    SharcResolveParameters r;
    r.cameraPositionPrev = gSharcPreviousCamera;
    r.accumulationFrameNum = gSharcHistory;
    r.responsiveFrameNum = 1;
    r.staleFrameNumMax = 60; // RTXGI Pathtracer UI default.
    r.frameIndex = gSharcFrame;
    SharcResolveEntry(tid.x, sharcParameters(), r);
    if (gSharcHash[tid.x] != 0)
    {
        InterlockedAdd(gSharcStats[2], 1u);
        if (!all(isfinite(float4(gSharcResolved[tid.x].radianceData)))) InterlockedAdd(gSharcStats[3], 1u);
    }
}
