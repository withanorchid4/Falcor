// Included after the shared Falcor material/lighting bridge.
// Coarse GBuffer paths maintain the cache independently of screen final gather.
float3 wcCosineDirection(float3 n, inout SampleGenerator sg)
{
    float2 u = sampleNext2D(sg);
    float3 t = normalize(cross(abs(n.z) < .999f ? float3(0, 0, 1) : float3(0, 1, 0), n));
    return t * (sqrt(u.x) * cos(2.f * M_PI * u.y)) + cross(n, t) * (sqrt(u.x) * sin(2.f * M_PI * u.y)) + n * sqrt(1.f - u.x);
}
[shader("raygeneration")]
void updateWorldCache()
{
    uint2 tile = DispatchRaysIndex().xy;
    SampleGenerator sg = SampleGenerator(tile, gFrameCount ^ 0xa51c3u);
    uint2 pixel = min(tile * gWCDownsample + uint2(sampleNext2D(sg) * float(gWCDownsample)), gFrameDim - 1u);
    HitInfo first = HitInfo(gVBuffer[pixel]);
    if (!first.isValid()) return;
    ShadingData primary = loadTriangleSurface(first, primaryRayDirection(pixel));
    if (!validSurface(primary)) return;
    // First version targets diffuse scenes. Material evaluation at cached vertices
    // uses Falcor diffuse albedo; specular/transmission transport is not cached.
    float3 normal = primary.getOrientedFaceNormal();
    RayDesc ray;
    ray.Origin = computeRayOrigin(primary.posW, normal);
    // Coverage proposal only: no primary BRDF/throughput is accumulated.
    ray.Direction = wcCosineDirection(normal, sg);
    ray.TMin = 0.f; ray.TMax = FLT_MAX;
    uint previous = WC_INVALID;
    float3 previousAlbedo = float3(0.f);
    for (uint bounce = 0; bounce <= gWCBounces; ++bounce)
    {
        ProbeRayPayload payload = {};
        payload.hitT = -1.f;
        TraceRay(gScene.rtAccel, RAY_FLAG_NONE, 0xff, 0, rayTypeCount, 0, ray, payload);
        if (payload.hitT < 0.f)
        {
            wcAccumulate(previous, previousAlbedo * evaluateProbeMiss(ray.Direction), 0u);
            break;
        }
        ShadingData sd = loadTriangleSurface(HitInfo(payload.hit), ray.Direction);
        if (!validSurface(sd) || (!sd.frontFacing && !sd.mtl.isDoubleSided())) break;
        float3 geometryNormal = sd.getOrientedFaceNormal();
        wcAccumulate(previous, previousAlbedo * wcLookup(sd.posW, geometryNormal), 0u);
        if (bounce == gWCBounces) break; // Terminal bootstrap; no truncated vertex estimate.
        let material = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f));
        let properties = material.getProperties(sd);
        uint slot = wcSlot(wcKey(sd.posW, geometryNormal), true);
        // Emissive geometry and environment are sampled by continuation rays.
        // Analytic-light NEE only: no duplicate emissive direct-light estimator.
        float3 direct = finiteRadiance(properties.emission, 0u) + evaluateAnalyticDirect(sd, material, true, sg);
        wcAccumulate(slot, direct, 1u);
        previous = slot;
        previousAlbedo = finiteRadiance(properties.diffuseReflectionAlbedo, 0u);
        if (!sampleDiffuseReflection(sd, properties, sg, ray.Direction)) break;
        ray.Origin = computeRayOrigin(sd.posW, geometryNormal);
    }
}
