// Real, orthonormal L2 SH. Directions and normals are in world space.
float probeSH(uint k, float3 d)
{
    switch (k)
    {
    case 0: return 0.2820947918f;
    case 1: return 0.4886025119f * d.y;
    case 2: return 0.4886025119f * d.z;
    case 3: return 0.4886025119f * d.x;
    case 4: return 1.0925484306f * d.x * d.y;
    case 5: return 1.0925484306f * d.y * d.z;
    case 6: return 0.3153915653f * (3.f * d.z * d.z - 1.f);
    case 7: return 1.0925484306f * d.x * d.z;
    default: return 0.5462742153f * (d.x * d.x - d.y * d.y);
    }
}

float probeCosineKernel(uint k)
{
    return k == 0 ? 3.1415926536f : (k < 4 ? 2.0943951024f : 0.7853981634f);
}
