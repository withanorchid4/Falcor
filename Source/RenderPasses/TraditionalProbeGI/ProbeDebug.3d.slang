// Instanced screen-space diagnostics. No scene or SH data is modified.
import ProbeSH;

cbuffer DebugCB
{
    float4x4 gViewProj;
    float3 gCameraPosition;
    float3 gCameraRight;
    float3 gCameraUp;
    float3 gCameraForward;
    float2 gDimensions;
    uint3 gCounts;
    float3 gMin;
    float3 gMax;
    uint gSamples;
    bool gReady;
    bool gShowProbes;
    bool gShowIds;
    bool gOnlyContributors;
    bool gShowBounds;
    bool gShowLinks;
    bool gXRay;
    bool gPreview;
    bool gRadiance;
    bool gNegative;
    uint gSelectedProbe;
    float gRadius;
    float gExposure;
}
StructuredBuffer<float4> gSH;
StructuredBuffer<float4> gInspection;
Texture2D<float> gDistance;

struct VertexOut
{
    float4 position : SV_Position;
    float2 local : TEXCOORD0;
    float3 world : TEXCOORD1;
    nointerpolation uint kind : TEXCOORD2;
    nointerpolation uint index : TEXCOORD3;
    nointerpolation float radius : TEXCOORD4;
    nointerpolation float worldRadius : TEXCOORD5;
    nointerpolation float3 color : TEXCOORD6;
    float inverseW : TEXCOORD7;
};

float3 probePosition(uint index)
{
    uint3 p = uint3(index % gCounts.x, (index / gCounts.x) % gCounts.y, index / (gCounts.x * gCounts.y));
    return lerp(gMin, gMax, float3(p) / float3(gCounts - 1));
}

bool project(float3 p, out float2 screen)
{
    float4 clip = mul(gViewProj, float4(p, 1));
    screen = (float2(clip.x, -clip.y) / max(clip.w, 1e-6f) * 0.5f + 0.5f) * gDimensions;
    return clip.w > 1e-5f && clip.z >= 0.f;
}

VertexOut vsMain(uint vertex : SV_VertexID, uint instance : SV_InstanceID)
{
    const float2 corners[6] = {float2(-1,-1), float2(1,-1), float2(-1,1),
        float2(-1,1), float2(1,-1), float2(1,1)};
    float2 q = corners[vertex];
    VertexOut o = (VertexOut)0;
    o.inverseW = 1.f;
    o.position = float4(2, 2, 0, 1); // Invisible unless configured below.
    uint count = gCounts.x * gCounts.y * gCounts.z;
    float3 spacing = (gMax - gMin) / float3(gCounts - 1);
    float radiusWorld = min(spacing.x, min(spacing.y, spacing.z)) * gRadius;
    float2 screen;
    if (instance < count || instance == count + 21 || instance == count + 22)
    {
        bool preview = instance == count + 22;
        bool marker = instance == count + 21;
        if (preview ? !gPreview : marker ? (!gShowLinks || gInspection[0].w == 0.f) : !gShowProbes) return o;
        if (!preview && !marker && gOnlyContributors && gInspection[0].w > 0.f)
        {
            bool contributing = false;
            for (uint j = 0; j < 8; ++j) contributing = contributing || uint(gInspection[4 + 3 * j].w) == instance;
            if (!contributing) return o;
        }
        o.index = preview ? gSelectedProbe : instance;
        o.kind = preview ? 2 : marker ? 3 : 0;
        o.world = marker ? gInspection[0].xyz : probePosition(o.index);
        o.worldRadius = marker ? 0.f : radiusWorld;
        float2 center, edge;
        if (preview)
        {
            o.radius = min(82.f, min(gDimensions.x, gDimensions.y) * 0.2f);
            center = gDimensions - float2(o.radius + 18.f);
        }
        else
        {
            if (!project(o.world, center) || !project(o.world + gCameraRight * radiusWorld, edge)) return o;
            o.radius = marker ? 4.f : clamp(length(edge - center), 3.f, 80.f);
        }
        float2 extent = float2(o.radius);
        if (gShowIds && !marker) extent = float2(max(o.radius, 20.f), o.radius + 14.f);
        o.local = q * extent;
        screen = center + o.local;
    }
    else
    {
        uint line = instance - count;
        float3 a, b;
        float thickness = 1.f;
        if (line < 12)
        {
            if (!gShowBounds) return o;
            uint axis = line / 4, edge = line % 4;
            float3 lo = float3(0);
            lo[(axis + 1) % 3] = float(edge & 1);
            lo[(axis + 2) % 3] = float((edge >> 1) & 1);
            float3 hi = lo;
            hi[axis] = 1.f;
            a = lerp(gMin, gMax, lo); b = lerp(gMin, gMax, hi);
            o.color = float3(0.05f, 0.5f, 1.f);
        }
        else
        {
            if (!gShowLinks || gInspection[0].w == 0.f) return o;
            if (line == 20)
            {
                a = gInspection[0].xyz; b = gInspection[2].xyz;
                o.color = float3(1.f, 0.8f, 0.02f);
                thickness = 2.f;
            }
            else
            {
                // Draw blocked links last so coincident visible links do not hide leakage evidence.
                uint rank = line - 12, corner = 0, cursor = 0;
                for (uint group = 0; group < 2; ++group)
                    for (uint j = 0; j < 8; ++j)
                        if ((gInspection[5 + 3 * j].y > 0.f ? 0u : 1u) == group)
                        {
                            if (cursor == rank) corner = j;
                            ++cursor;
                        }
                float4 data = gInspection[5 + 3 * corner];
                if (data.z < 1e-6f) return o;
                a = gInspection[2].xyz; b = gInspection[4 + 3 * corner].xyz;
                o.color = data.y > 0.f ? float3(0.02f, 1.f, 0.12f) : float3(1.f, 0.015f, 0.01f);
                thickness = 1.f + 4.f * data.x; // Keep rejected links visible at minimum thickness.
            }
        }
        float2 sa, sb;
        if (!project(a, sa) || !project(b, sb)) return o;
        float2 delta = sb - sa;
        if (dot(delta, delta) < 0.01f) return o;
        float2 perpendicular = normalize(float2(-delta.y, delta.x));
        float t = q.x * 0.5f + 0.5f;
        screen = lerp(sa, sb, t) + perpendicular * q.y * thickness;
        // Perspective-correct world interpolation even though the ribbon is defined in pixels.
        float wa = mul(gViewProj, float4(a, 1)).w;
        float wb = mul(gViewProj, float4(b, 1)).w;
        o.world = lerp(a / wa, b / wb, t);
        o.inverseW = lerp(1.f / wa, 1.f / wb, t);
        o.kind = 1;
    }
    o.position = float4(screen / gDimensions * float2(2, -2) + float2(-1, 1), 0, 1);
    return o;
}

// Tiny seven-segment ID labels; drawing cost stays one instanced pass.
bool digitPixel(uint digit, float2 p)
{
    const uint masks[10] = {63, 6, 91, 79, 102, 109, 125, 7, 127, 111};
    uint mask = masks[digit];
    bool on = false;
    on = on || ((mask & 1) != 0 && p.y < 1 && p.x >= 1 && p.x < 4);
    on = on || ((mask & 2) != 0 && p.x >= 4 && p.y >= 1 && p.y < 4);
    on = on || ((mask & 4) != 0 && p.x >= 4 && p.y >= 4 && p.y < 7);
    on = on || ((mask & 8) != 0 && p.y >= 7 && p.x >= 1 && p.x < 4);
    on = on || ((mask & 16) != 0 && p.x < 1 && p.y >= 4 && p.y < 7);
    on = on || ((mask & 32) != 0 && p.x < 1 && p.y >= 1 && p.y < 4);
    on = on || ((mask & 64) != 0 && p.y >= 3 && p.y < 4 && p.x >= 1 && p.x < 4);
    return on && all(p >= 0) && p.x < 5 && p.y < 8;
}

bool idPixel(uint id, float2 local, float radius)
{
    uint digits = id >= 10000 ? 5 : id >= 1000 ? 4 : id >= 100 ? 3 : id >= 10 ? 2 : 1;
    float2 p = local + float2(float(digits) * 3.f, radius + 11.f);
    if (p.x < 0 || p.x >= float(digits) * 6.f || p.y < 0 || p.y >= 8.f) return false;
    uint column = uint(p.x / 6.f);
    uint divisor = 1;
    for (uint i = column + 1; i < digits; ++i) divisor *= 10;
    return digitPixel((id / divisor) % 10, float2(fmod(p.x, 6.f), p.y));
}

float4 psMain(VertexOut i) : SV_Target0
{
    float3 world = i.world / i.inverseW;
    float3 color = i.color;
    if (i.kind == 0 || i.kind == 2 || i.kind == 3)
    {
        float2 q = i.local / i.radius;
        float r2 = dot(q, q);
        bool label = gShowIds && i.kind != 3 && idPixel(i.index, i.local, i.radius);
        if (r2 > 1.f && !label) discard;
        float z = sqrt(max(0.f, 1.f - r2));
        float3 n = normalize(q.x * gCameraRight - q.y * gCameraUp - z * gCameraForward);
        world += n * i.worldRadius;
        if (label) color = float3(2.f);
        else if (i.kind == 3) color = float3(1.f, 0.8f, 0.02f);
        else if (!gReady) color = float3(0.12f + 0.2f * z);
        else
        {
            float3 value = float3(0);
            for (uint k = 0; k < 9; ++k)
                value += gSH[i.index * 9 + k].xyz * probeSH(k, n) *
                    (gRadiance ? 1.f : probeCosineKernel(k)) / float(gSamples);
            color = gNegative && any(value < 0.f) ? float3(2.f, 0, 2.f) : max(value, float3(0)) * gExposure;
        }
        if (!label && i.kind != 3 && r2 > 0.88f)
            color = i.index == gSelectedProbe ? float3(2.f, 1.4f, 0) : float3(0.25f);
    }
    if (!gXRay && i.kind != 2)
    {
        float distance = length(world - gCameraPosition);
        float sceneDistance = gDistance[uint2(i.position.xy)];
        if (distance > sceneDistance + max(1e-4f, sceneDistance * 1e-4f)) discard;
    }
    return float4(color, 1);
}
