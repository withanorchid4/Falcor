# Adapt the deployed SDK copy; the downloaded NVIDIA source remains intact.
file(READ "${SDK}/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl" code)
set(anchor "    // Iterate over the 8 closest probes and accumulate their contributions")
string(FIND "${code}" "${anchor}" found)
if(found EQUAL -1)
    message(FATAL_ERROR "DDGI tetrahedral insertion anchor changed")
endif()
string(REPLACE "${anchor}" [=[
#if DDGI_TETRAHEDRAL
    // Six tetrahedra share the 000--111 body diagonal. Opposite tie priorities
    // keep maximum/minimum axes distinct, including at equal coordinates.
    int maxAxis = (alpha.x >= alpha.y && alpha.x >= alpha.z) ? 0 : ((alpha.y >= alpha.z) ? 1 : 2);
    int minAxis = (alpha.z <= alpha.x && alpha.z <= alpha.y) ? 2 : ((alpha.y <= alpha.x) ? 1 : 0);
    int3 maxCorner = int3(maxAxis == 0, maxAxis == 1, maxAxis == 2);
    int3 minCorner = int3(minAxis == 0, minAxis == 1, minAxis == 2);
    float aMax = max(alpha.x,max(alpha.y,alpha.z));
    float aMin = min(alpha.x,min(alpha.y,alpha.z));
    float aMid = alpha.x + alpha.y + alpha.z - aMax - aMin;
#endif
    // Iterate over the selected corners and accumulate their contributions
]=] code "${code}")
string(REPLACE "probeIndex < 8" "probeIndex < (DDGI_TETRAHEDRAL ? 4 : 8)" code "${code}")
set(anchor "int3 adjacentProbeOffset = int3(probeIndex, probeIndex >> 1, probeIndex >> 2) & int3(1, 1, 1);")
string(REPLACE "${anchor}" [=[
#if DDGI_TETRAHEDRAL
        int3 adjacentProbeOffset = probeIndex == 0 ? int3(0,0,0) : (probeIndex == 1 ? maxCorner : (probeIndex == 2 ? int3(1,1,1)-minCorner : int3(1,1,1)));
#else
        int3 adjacentProbeOffset = int3(probeIndex, probeIndex >> 1, probeIndex >> 2) & int3(1, 1, 1);
#endif
]=] code "${code}")
set(anchor "float  trilinearWeight = (trilinear.x * trilinear.y * trilinear.z);")
string(REPLACE "${anchor}" [=[
#if DDGI_TETRAHEDRAL
        float trilinearWeight = max(0.f,probeIndex == 0 ? 1.f-aMax : (probeIndex == 1 ? aMax-aMid : (probeIndex == 2 ? aMid-aMin : aMin)));
        // Exact zero on shared faces preserves continuity. Do not floor this weight.
        if (trilinearWeight == 0.f) continue;
#else
        float trilinearWeight = (trilinear.x * trilinear.y * trilinear.z);
#endif
]=] code "${code}")
# Optional arithmetic-only adaptations, retaining a diagnostic baseline.
string(REPLACE "    // Iterate over the selected corners and accumulate their contributions" [=[
#if DDGI_HOIST_NORMAL_OCT
    float2 queryNormalOct = DDGIGetOctahedralCoordinates(direction);
#endif
    // Iterate over the selected corners and accumulate their contributions
]=] code "${code}")
string(REPLACE "float3 biasedPosToAdjProbe = normalize(adjacentProbeWorldPosition - biasedWorldPosition);" [=[
#if DDGI_SKIP_DIRECTION_NORMALIZE
        float3 biasedPosToAdjProbe = adjacentProbeWorldPosition - biasedWorldPosition;
#else
        float3 biasedPosToAdjProbe = normalize(adjacentProbeWorldPosition - biasedWorldPosition);
#endif
]=] code "${code}")
string(REPLACE "octantCoords = DDGIGetOctahedralCoordinates(direction);" [=[
#if DDGI_HOIST_NORMAL_OCT
        octantCoords = queryNormalOct;
#else
        octantCoords = DDGIGetOctahedralCoordinates(direction);
#endif
]=] code "${code}")
file(WRITE "${OUTPUT}/IrradianceTetrahedral.hlsl" "// Generated optional tetrahedral query; NVIDIA license preserved below.\n#ifndef DDGI_TETRAHEDRAL\n#define DDGI_TETRAHEDRAL 0\n#endif\n${code}")
