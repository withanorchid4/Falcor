// Octahedral coordinates use +Z at the center and -Z at the four corners.
uint probeDistanceHash(uint x)
{
    x ^= x >> 16; x *= 0x7feb352du;
    x ^= x >> 15; x *= 0x846ca68bu;
    return x ^ (x >> 16);
}

// Absolute sample indices keep the sphere samples independent of frame batching.
float3 probeDistanceRayDirection(uint probe, uint sampleIndex)
{
    uint seed = probeDistanceHash(probe ^ 0x9e3779b9u) ^ probeDistanceHash(sampleIndex);
    float u = float(probeDistanceHash(seed) >> 8) * (1.f / 16777216.f);
    float v = float(probeDistanceHash(seed ^ 0x68bc21ebu) >> 8) * (1.f / 16777216.f);
    float z = 1.f - 2.f * u;
    float r = sqrt(max(0.f, 1.f - z * z));
    float phi = 6.28318530718f * v;
    return float3(r * cos(phi), r * sin(phi), z);
}

float2 probeSignNotZero(float2 v)
{
    return float2(v.x >= 0.f ? 1.f : -1.f, v.y >= 0.f ? 1.f : -1.f);
}

float2 probeOctEncode(float3 direction)
{
    float3 p = direction / max(abs(direction.x) + abs(direction.y) + abs(direction.z), 1e-20f);
    float2 q = p.xy;
    if (p.z < 0.f) q = (1.f - abs(q.yx)) * probeSignNotZero(q);
    return q * 0.5f + 0.5f;
}

float3 probeOctDecode(float2 uv)
{
    float2 p = uv * 2.f - 1.f;
    float3 n = float3(p, 1.f - abs(p.x) - abs(p.y));
    if (n.z < 0.f) n.xy = (1.f - abs(n.yx)) * probeSignNotZero(n.xy);
    return normalize(n);
}

// Reflect across octahedron seams; works for the one-texel padding, including corners.
int2 probeOctWrap(int2 p, int size)
{
    if (p.x < 0) { p.x = 0; p.y = size - 1 - p.y; }
    else if (p.x >= size) { p.x = size - 1; p.y = size - 1 - p.y; }
    if (p.y < 0) { p.y = 0; p.x = size - 1 - p.x; }
    else if (p.y >= size) { p.y = size - 1; p.x = size - 1 - p.x; }
    return p;
}

float probeChebyshev(float query, float2 moments, float varianceBase, float power)
{
    float delta = max(query - moments.x, 0.f);
    float variance = max(moments.y - moments.x * moments.x, 0.f) + varianceBase;
    return pow(variance / (variance + delta * delta), power);
}
