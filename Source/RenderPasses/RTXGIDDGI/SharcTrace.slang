// This software contains source code provided by NVIDIA Corporation.
// Control-flow baseline: RTXGI 04372d7f Samples/Pathtracer/Shaders/Pathtracer.hlsl.
// Falcor bridge is currently validated for Lambert reflection only.
float sharcLuminance(float3 value) { return dot(value,float3(.2126f,.7152f,.0722f)); }

// The common FG has already shaded/sampled camera vertex 0. Continue at vertex 1.
float3 sharcQueryPath(ShadingData sd, float segmentLength, float3 primaryWeight, inout SampleGenerator sg)
{
    float3 result = float3(0.f), weight = float3(1.f);
    if (sharcLuminance(primaryWeight) < .01f) return result;
    for (uint bounce = 1; bounce < gSharcBounces; ++bounce)
    {
        if (!validSurface(sd) || (!sd.frontFacing && !sd.mtl.isDoubleSided())) break;
        float3 n = sd.getOrientedFaceNormal(), cached;
        let material = gScene.materials.getMaterialInstance(sd, ExplicitLodTextureSampler(0.f));
        let properties = material.getProperties(sd);
        SharcHitData hitData = sharcHit(sd.posW,n,properties.diffuseReflectionAlbedo);
        SharcParameters params = sharcParameters();
        float cell = HashGridGetVoxelSize(HashGridGetLevel(sd.posW, params.hashGridParameters), params.hashGridParameters);
        // Official segment and roughness footprint tests. Preceding Lambert
        // reflection contributes 1 to roughness, clamped by the sample to .99.
        float alpha = .99f * .99f;
        float footprint = segmentLength * sqrt(.5f * alpha * alpha / (1.f - alpha * alpha));
        if (segmentLength > cell * sqrt(3.f) && footprint > cell && sharcLookup(hitData,cached))
        {
            result += weight * cached; break;
        }
        result += weight * (finiteRadiance(properties.emission,0u) + evaluateAnalyticDirect(sd,material,true,sg));
        if (bounce == gSharcBounces - 1u) break;
        if (bounce > 3u)
        {
            float probability = min(.95f,sharcLuminance(weight*primaryWeight));
            if (probability <= 0.f || probability < sampleNext1D(sg)) break;
            weight /= probability;
        }
        RayDesc ray;
        ray.Origin = computeRayOrigin(sd.posW,n);
        ray.TMin = 0.f; ray.TMax = 1000.f;
        if (!sampleDiffuseReflection(sd, properties, sg, ray.Direction)) break;
        weight *= finiteRadiance(properties.diffuseReflectionAlbedo,0u);
        if (sharcLuminance(weight*primaryWeight) < .01f) break;
        ProbeRayPayload hit = {}; hit.hitT = -1.f;
        TraceRay(gScene.rtAccel,RAY_FLAG_NONE,0xff,0,rayTypeCount,0,ray,hit);
        if (hit.hitT < 0.f) { result += weight*evaluateProbeMiss(ray.Direction); break; }
        segmentLength = hit.hitT;
        sd = loadTriangleSurface(HitInfo(hit.hit),ray.Direction);
    }
    return finiteRadiance(result,0u);
}

[shader("raygeneration")]
void updateSharcCache()
{
    uint2 tile = DispatchRaysIndex().xy;
    SampleGenerator sg = SampleGenerator(tile,gFrameCount ^ 0xa51c3u);
    // Official reduced-resolution camera path with shared per-frame jitter,
    // including the primary hit in SharcUpdateHit().
    float2 uv = (float2(tile)+.5f-gSharcPixelOffset)/float2(DispatchRaysDimensions().xy);
    float2 ndc = uv*float2(2,-2)+float2(-1,1);
    RayDesc ray;
    ray.Origin = gScene.camera.getPosition();
    ray.Direction = normalize(ndc.x*gScene.camera.data.cameraU + ndc.y*gScene.camera.data.cameraV + gScene.camera.data.cameraW);
    ray.TMin = 0.f; ray.TMax = 1000.f;
    SharcState state; SharcInit(state);
    SharcParameters params = sharcParameters();
    for (uint bounce = 0; bounce < gSharcBounces; ++bounce)
    {
        ProbeRayPayload hit = {}; hit.hitT = -1.f;
        TraceRay(gScene.rtAccel,RAY_FLAG_NONE,0xff,0,rayTypeCount,0,ray,hit);
        if (hit.hitT < 0.f) { SharcUpdateMiss(params,state,evaluateProbeMiss(ray.Direction)); break; }
        ShadingData sd = loadTriangleSurface(HitInfo(hit.hit),ray.Direction);
        if (!validSurface(sd) || (!sd.frontFacing && !sd.mtl.isDoubleSided())) break;
        float3 n = sd.getOrientedFaceNormal();
        // This update path starts at the camera, just like PathTracer. Secondary
        // vertices retain the default unadjusted material policy.
        uint hints = bounce == 0u ? primaryMaterialHints() : 0u;
        let material = gScene.materials.getMaterialInstance(sd,ExplicitLodTextureSampler(0.f),hints);
        let properties = material.getProperties(sd);
        float3 direct = finiteRadiance(properties.emission,0u) + evaluateAnalyticDirect(sd,material,true,sg);
        // Match sample ordering: max-vertex termination precedes UpdateHit.
        // No custom terminal cache query/bootstrap.
        if (bounce == gSharcBounces - 1u) break;
        if (!SharcUpdateHit(params,state,sharcHit(sd.posW,n,properties.diffuseReflectionAlbedo),direct,sampleNext1D(sg))) break;
        float3 segmentWeight = float3(1.f); // Update resets throughput each vertex.
        if (bounce > 3u)
        {
            if (.95f < sampleNext1D(sg)) break;
            segmentWeight /= .95f;
        }
        if (!sampleDiffuseReflection(sd, properties, sg, ray.Direction)) break;
        SharcSetThroughput(state,segmentWeight*finiteRadiance(properties.diffuseReflectionAlbedo,0u));
        ray.Origin = computeRayOrigin(sd.posW,n);
    }
}
