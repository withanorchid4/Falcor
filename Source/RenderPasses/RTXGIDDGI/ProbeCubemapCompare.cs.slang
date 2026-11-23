import Scene.Scene;
Texture2DArray<uint4> gReference;
Texture2DArray<uint4> gCurrent;
RWByteAddressBuffer gDifference;
cbuffer CompareCB
{
    uint gSize;
    uint gLayers;
}
[numthreads(8, 8, 1)] void main(uint3 tid : SV_DispatchThreadID) {
    if (tid.x >= gSize || tid.y >= gSize || tid.z >= gLayers)
        return;
    uint4 a = gReference.Load(int4(tid, 0)), b = gCurrent.Load(int4(tid, 0));
#if HIT_INFO_USE_COMPRESSION
    HitInfo A = HitInfo(a.xy), B = HitInfo(b.xy);
#else
    HitInfo A = HitInfo(a), B = HitInfo(b);
#endif
    if (A.isValid())
        gDifference.InterlockedAdd(0, 1);
    if (A.isValid() != B.isValid())
    {
        gDifference.InterlockedAdd(A.isValid() ? 4 : 8, 1);
        return;
    }
    if (!A.isValid())
        return;
    if (gScene.getMaterialID(A.getTriangleHit().instanceID) != gScene.getMaterialID(B.getTriangleHit().instanceID))
        gDifference.InterlockedAdd(24, 1);
    float3 pa = gScene.getVertexData(A.getTriangleHit()).posW, pb = gScene.getVertexData(B.getTriangleHit()).posW;
    float e = length(pa - pb);
    if (!isfinite(e))
    {
        gDifference.InterlockedAdd(20, 1);
        return;
    }
    if (e > 0.001f)
    {
        gDifference.InterlockedAdd(12, 1);
        if (A.getTriangleHit().instanceID.index == B.getTriangleHit().instanceID.index &&
            A.getTriangleHit().primitiveIndex == B.getTriangleHit().primitiveIndex)
            gDifference.InterlockedAdd(28, 1);
    }
    gDifference.InterlockedMax(16, asuint(e));
}
