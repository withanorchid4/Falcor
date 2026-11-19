// Experimental DDGI-backed screen-space reservoir gather.
// Independent Falcor implementation of the Lumen gather stages, not UE shader code.
#if RESTIR_GATHER
struct GatherReservoir
{
    float4 hit;       // xyz: world hit position, or environment direction; w: finite hit
    float4 radiance;  // xyz: outgoing radiance, w: positive luminance target
    float4 normalW;   // xyz: hit normal; w: reservoir normalization W (solid angle)
    float4 originM;   // xyz: primary position; w: effective candidate count M
    float4 surface;   // xyz: primary shading normal; w: camera distance (0 = invalid)
    float4 geometryAge; // xyz: oriented primary geometric normal; w: selected sample age
};
StructuredBuffer<GatherReservoir> gReservoirInput, gReservoirHistory, gReservoirTemporal;
RWStructuredBuffer<GatherReservoir> gReservoirOutput;
#if RESTIR_MOTION
Texture2D<float2> gMotionVectors;
#endif
#if OUTPUT_RESTIR_DEBUG
RWTexture2D<float4> gRestirDebug;
#endif
uint reservoirIndex(uint2 p) { return p.y * gRestirDim.x + p.x; }
uint2 reservoirPixel(uint2 p) { return min(p * (gHalfResolutionGather ? 2u : 1u) + gGatherOffset, gFrameDim - 1u); }
float sampleTarget(float3 c) { return max(dot(c, float3(.2126f,.7152f,.0722f)), 1e-6f); }
float3 reservoirDirection(GatherReservoir r, float3 x)
{
    return r.hit.w > 0.f ? normalize(r.hit.xyz - x) : r.hit.xyz;
}
bool validReservoir(GatherReservoir r)
{
    return r.originM.w > 0.f && r.radiance.w > 0.f && r.normalW.w >= 0.f &&
        all(isfinite(r.hit)) && all(isfinite(r.radiance)) && all(isfinite(r.normalW)) &&
        all(isfinite(r.originM)) && all(isfinite(r.surface)) && all(isfinite(r.geometryAge));
}
bool compatibleSurface(float3 p, float3 n, float depth, GatherReservoir r)
{
    if (!validReservoir(r) || r.surface.w <= 0.f || dot(n, r.surface.xyz) < .95f) return false;
    return abs(dot(p - r.originM.xyz, n)) < max(.002f, .005f * depth);
}
// dOmega_destination / dOmega_source for reconnecting the same secondary hit.
float reconnectJacobian(GatherReservoir r, float3 x, float3 n)
{
    float3 direction = reservoirDirection(r, x);
    if (dot(n, direction) <= 0.f) return 0.f;
    if (r.hit.w == 0.f) return 1.f;
    float3 a = r.originM.xyz - r.hit.xyz, b = x - r.hit.xyz;
    float a2 = dot(a,a), b2 = dot(b,b);
    if (min(a2,b2) < 1e-10f) return 0.f;
    float ca = dot(r.normalW.xyz, a * rsqrt(a2));
    float cb = dot(r.normalW.xyz, b * rsqrt(b2));
    ca = gRestirBiasCorrection ? max(ca, 0.f) : abs(ca);
    cb = gRestirBiasCorrection ? max(cb, 0.f) : abs(cb);
    float j = cb * a2 / max(ca * b2, 1e-12f);
    // The local UE reference likewise rejects extreme Jacobians. This is a
    // deliberate practical bias; this screen-space reuse is not claimed unbiased.
    return isfinite(j) && j >= .1f && j <= 10.f ? j : 0.f;
}
// Both forward reconnection and reverse source evaluation call this exact
// visibility query, with the source's GEOMETRIC normal and identical endpoint rules.
bool visibleFrom(GatherReservoir r, float3 position, float3 geometricNormal)
{
    float3 direction = reservoirDirection(r, position);
    if (!all(isfinite(direction)) || dot(geometricNormal, direction) <= kMinCosTheta) return false;
    float3 origin = computeRayOrigin(position, geometricNormal);
    if (r.hit.w == 0.f) return traceShadow(origin, direction, FLT_MAX);
    float3 segment = r.hit.xyz - origin;
    float d = length(segment);
    return d > 1e-5f && traceShadow(origin, segment / d, max(0.f, d - max(1e-4f, d * 1e-4f)));
}
bool reservoirVisible(GatherReservoir r, ShadingData sd)
{
    return visibleFrom(r, sd.posW, sd.getOrientedFaceNormal());
}
bool sourceSupports(GatherReservoir selected, GatherReservoir destination, GatherReservoir source)
{
    selected.originM.xyz = destination.originM.xyz;
    if (reconnectJacobian(selected, source.originM.xyz, source.surface.xyz) <= 0.f) return false;
    return visibleFrom(selected, source.originM.xyz, source.geometryAge.xyz);
}
// Return whether this source supplied the selected sample. Source identity is
// required by the NVIDIA-style MIS normalization numerator, not just its sum.
bool mergeReservoir(inout GatherReservoir selected, inout float sum, inout float count,
                    GatherReservoir candidate, float jacobian, float noise)
{
    if (!validReservoir(candidate)) { rejectNonFinite(3u); return false; }
    // Avoid 0 * Inf and never carry a non-finite reservoir into temporal history.
    float weight = jacobian > 0.f ? candidate.radiance.w * candidate.normalW.w * candidate.originM.w * jacobian : 0.f;
    if (!isfinite(weight) || !isfinite(sum + weight)) { rejectNonFinite(3u); return false; }
    count += candidate.originM.w;
    sum += weight;
    bool changed = weight > 0.f && noise * sum < weight;
    if (changed) selected = candidate;
    return changed;
}
GatherReservoir finishReservoir(GatherReservoir selected, GatherReservoir source, float sum,
                                float count, float normalizationCount, float selectedSourceSupport)
{
    // For our shared luminance target p: pi = p * selectedSourceSupport,
    // piSum = p * normalizationCount. W = sum*pi/(p*piSum).
    // The numerator may NOT be cancelled if the selected source has zero support.
    float denominator = normalizationCount * selected.radiance.w;
    float w = selectedSourceSupport > 0.f && denominator > 0.f ? (sum / denominator) * selectedSourceSupport : 0.f;
    if (!isfinite(w)) { rejectNonFinite(3u); w = 0.f; }
    selected.normalW.w = w;
    selected.originM = float4(source.originM.xyz, count);
    selected.surface = source.surface;
    selected.geometryAge.xyz = source.geometryAge.xyz;
    return selected;
}

[shader("raygeneration")]
void restirInitial()
{
    uint2 coord = DispatchRaysIndex().xy, pixel = reservoirPixel(coord);
    GatherReservoir r = {};
    HitInfo h = HitInfo(gVBuffer[pixel]);
    if (h.isValid())
    {
        ShadingData sd = loadTriangleSurface(h, primaryRayDirection(pixel));
        if (validSurface(sd))
        {
            SampleGenerator sg = SampleGenerator(pixel, gFrameCount);
            float2 u = sampleNext2D(sg);
            float z = u.x, radius = sqrt(max(0.f, 1.f - z*z)), phi = 2.f * M_PI * u.y;
            float3 direction = normalize(sd.frame.fromLocal(float3(radius*cos(phi), radius*sin(phi), z)));
            r.hit = float4(direction, 0.f);
            r.originM = float4(sd.posW, 1.f);
            r.surface = float4(sd.frame.N, length(sd.posW - gScene.camera.getPosition()));
            r.geometryAge = float4(sd.getOrientedFaceNormal(), 0.f);
            r.normalW.w = 2.f * M_PI; // uniform hemisphere proposal, 1 / q
            float3 radiance = 0.f;
            if (dot(sd.getOrientedFaceNormal(), direction) > kMinCosTheta)
            {
                RayDesc ray;
                ray.Origin = computeRayOrigin(sd.posW, dot(sd.faceN,direction)>=0.f ? sd.faceN : -sd.faceN);
                ray.Direction = direction; ray.TMin = 0.f; ray.TMax = FLT_MAX;
                ProbeRayPayload payload = {}; payload.hitT = -1.f;
                TraceRay(gScene.rtAccel, RAY_FLAG_NONE, 0xff, 0, rayTypeCount, 0, ray, payload);
                if (payload.hitT < 0.f) radiance = evaluateProbeMiss(direction);
                else
                {
                    ShadingData hit = loadTriangleSurface(HitInfo(payload.hit), direction);
                    if (validSurface(hit))
                    {
                        r.hit = float4(hit.posW, 1.f);
                        r.normalW.xyz = hit.getOrientedFaceNormal();
                        let material = gScene.materials.getMaterialInstance(hit, ExplicitLodTextureSampler(0.f));
                        let properties = material.getProperties(hit);
                        radiance = finiteRadiance(properties.emission, 0u) + evaluateDirect(hit, material, false, sg);
                        radiance += finiteRadiance(properties.diffuseReflectionAlbedo,0u) *
                            queryIrradiance(hit.posW, hit.getOrientedFaceNormal(), direction, UnpackDDGIVolumeDescGPU(DDGIVolumes[0])) / M_PI;
                    }
                }
            }
            radiance = finiteRadiance(radiance,3u);
            r.radiance = float4(radiance, sampleTarget(radiance));
        }
    }
    gReservoirOutput[reservoirIndex(coord)] = r;
}

[shader("raygeneration")]
void restirTemporal()
{
    uint2 coord = DispatchRaysIndex().xy, pixel = reservoirPixel(coord);
    uint index = reservoirIndex(coord);
    GatherReservoir fresh = gReservoirInput[index], selected = fresh;
    float count = fresh.originM.w, sum = fresh.radiance.w * fresh.normalW.w * count;
    GatherReservoir historySource = {};
    bool hasHistorySource = false, selectedHistory = false;
    if (fresh.surface.w > 0.f && gRestirHistoryValid)
    {
        float4 clip = mul(gRestirPreviousViewProj, float4(fresh.originM.xyz,1.f));
        float2 uv = clip.xy / max(clip.w,1e-20f) * float2(.5f,-.5f) + .5f;
#if RESTIR_MOTION
        uv = (float2(pixel)+.5f)/float2(gFrameDim) + gMotionVectors[pixel];
#endif
        if (clip.w > 0.f && all(uv>=0.f) && all(uv<1.f))
        {
            int factor = gHalfResolutionGather ? 2 : 1;
            int2 base = int2(round((uv * float2(gFrameDim) - .5f - float2(gRestirPreviousOffset)) / float(factor)));
            float best = pow(max(.01f, .03f*fresh.surface.w),2.f);
            int found = -1;
            if (gRestirTemporalCellMapping)
            {
                // Reservoirs belong to coarse cells, not the moving sample lattice.
                // Preserve cell identity under static-camera subpixel jitter. Try
                // the projected cell first; neighbors are disocclusion fallbacks.
                base = int2(floor(uv * float2(gFrameDim) / float(factor)));
                const int2 ring[8] = { int2(-1,-1),int2(0,-1),int2(1,-1),int2(1,0),
                    int2(1,1),int2(0,1),int2(-1,1),int2(-1,0) };
                SampleGenerator searchRng = SampleGenerator(pixel, gFrameCount ^ 0xa511e9b3u);
                uint start = min(uint(sampleNext1D(searchRng)*8.f),7u);
                for (uint i=0;i<9u;i++)
                {
                    int2 c = base + (i == 0u ? int2(0) : ring[(start+i-1u)&7u]);
                    if (any(c<0) || any(c>=int2(gRestirDim))) continue;
                    GatherReservoir old = gReservoirHistory[reservoirIndex(uint2(c))];
                    float3 delta = old.originM.xyz - fresh.originM.xyz;
                    if (compatibleSurface(fresh.originM.xyz,fresh.surface.xyz,fresh.surface.w,old) && dot(delta,delta)<best)
                    { found=int(reservoirIndex(uint2(c))); break; }
                }
            }
            else
            {
                // Legacy nearest-world-point search, retained for regression tests.
                for (int y=-1;y<=1;y++) for (int x=-1;x<=1;x++)
                {
                    int2 c = base + int2(x,y);
                    if (any(c<0) || any(c>=int2(gRestirDim))) continue;
                    GatherReservoir old = gReservoirHistory[reservoirIndex(uint2(c))];
                    float3 delta = old.originM.xyz - fresh.originM.xyz;
                    float distance2 = dot(delta,delta);
                    if ((gRestirMaxAge == 0u || old.geometryAge.w < float(gRestirMaxAge)) &&
                        compatibleSurface(fresh.originM.xyz,fresh.surface.xyz,fresh.surface.w,old) && distance2 < best)
                    { found = int(reservoirIndex(uint2(c))); best=distance2; }
                }
            }
            if (found >= 0)
            {
                GatherReservoir old = gReservoirHistory[found];
                old.originM.w = min(old.originM.w, float(gRestirHistoryLength - 1u));
                old.geometryAge.w += 1.f;
                ShadingData sd = loadTriangleSurface(HitInfo(gVBuffer[pixel]), primaryRayDirection(pixel));
                float j = reconnectJacobian(old, fresh.originM.xyz, fresh.surface.xyz);
                bool visible = j > 0.f && reservoirVisible(old,sd);
                if ((gRestirMaxAge == 0u || old.geometryAge.w <= float(gRestirMaxAge)) &&
                    old.originM.w > 0.f && (gRestirBiasCorrection || visible))
                {
                    historySource = old; hasHistorySource = true;
                    SampleGenerator sg = SampleGenerator(pixel, gFrameCount ^ 0x80000000u);
                    selectedHistory = mergeReservoir(selected,sum,count,old,visible ? j : 0.f,sampleNext1D(sg));
                }
            }
        }
    }
    float normalizationCount = count, selectedSourceSupport = 1.f;
    if (gRestirBiasCorrection && hasHistorySource)
    {
        bool supported = sourceSupports(selected,fresh,historySource);
        normalizationCount = fresh.originM.w + (supported ? historySource.originM.w : 0.f);
        if (selectedHistory) selectedSourceSupport = supported ? 1.f : 0.f;
    }
    GatherReservoir result = count > 0.f ? finishReservoir(selected,fresh,sum,count,normalizationCount,selectedSourceSupport) : fresh;
    gReservoirOutput[index] = result;
}

[shader("raygeneration")]
void restirSpatial()
{
    uint2 coord=DispatchRaysIndex().xy, pixel=reservoirPixel(coord);
    uint index=reservoirIndex(coord);
    GatherReservoir center=gReservoirInput[index], selected=center;
    float count=center.originM.w, sum=center.radiance.w * center.normalW.w * count;
    uint sources[16];
    uint sourceCount = 0;
    int selectedSource = -1;
    if (center.surface.w > 0.f)
    {
        ShadingData sd=loadTriangleSurface(HitInfo(gVBuffer[pixel]),primaryRayDirection(pixel));
        SampleGenerator sg=SampleGenerator(pixel,gFrameCount ^ (0x40000000u + gRestirSpatialPassIndex*0x10000000u));
        float rotation=sampleNext1D(sg)*2.f*M_PI;
        for (uint i=0;i<gRestirSpatialSamples;i++)
        {
            float angle=rotation+float(i)*2.39996323f;
            float radius=sqrt((float(i)+.5f)/max(float(gRestirSpatialSamples),1.f))*gRestirSpatialRadius;
            int2 offset=int2(round(float2(cos(angle),sin(angle))*radius));
            int2 c=int2(coord)+offset;
            if (all(offset==0) || any(c<0) || any(c>=int2(gRestirDim))) continue;
            GatherReservoir other=gReservoirInput[reservoirIndex(uint2(c))];
            if (!compatibleSurface(center.originM.xyz,center.surface.xyz,center.surface.w,other)) continue;
            float j=reconnectJacobian(other,center.originM.xyz,center.surface.xyz);
            bool visible = j>0.f && reservoirVisible(other,sd);
            if (gRestirBiasCorrection || visible)
            {
                sources[sourceCount] = reservoirIndex(uint2(c));
                if (mergeReservoir(selected,sum,count,other,visible ? j : 0.f,sampleNext1D(sg))) selectedSource = int(sourceCount);
                sourceCount++;
            }
        }
    }
    float normalizationCount = count, selectedSourceSupport = 1.f;
    if (gRestirBiasCorrection)
    {
        normalizationCount = center.originM.w;
        for (uint i=0;i<sourceCount;i++)
        {
            GatherReservoir source = gReservoirInput[sources[i]];
            bool supported = sourceSupports(selected,center,source);
            if (supported) normalizationCount += source.originM.w;
            if (selectedSource == int(i)) selectedSourceSupport = supported ? 1.f : 0.f;
        }
    }
    GatherReservoir result = count>0.f ? finishReservoir(selected,center,sum,count,normalizationCount,selectedSourceSupport) : center;
    result.originM.w = count;
    gReservoirOutput[index] = result;
}

[shader("raygeneration")]
void restirIntegrate()
{
    uint2 dispatchPixel=DispatchRaysIndex().xy;
    uint2 pixel=gRestirFullResolution ? dispatchPixel : reservoirPixel(dispatchPixel);
    uint2 outputPixel=gRestirFullResolution || !gHalfResolutionGather ? pixel : dispatchPixel;
    float3 diffuse=0.f, specular=0.f;
    float distance=0.f, specDistance=0.f, total=0.f;
    uint accepted=0;
    HitInfo h=HitInfo(gVBuffer[pixel]);
    if (h.isValid())
    {
        ShadingData sd=loadTriangleSurface(h,primaryRayDirection(pixel));
        let material=gScene.materials.getMaterialInstance(sd,ExplicitLodTextureSampler(0.f),primaryMaterialHints());
        let props=material.getProperties(sd);
        uint lobes=material.getLobeTypes(sd);
        bool sharpSpecular=props.roughness < .2f || (lobes & (uint)LobeType::DeltaReflection)!=0;
        ShadingData diffuseSD=sd, specularSD=sd;
        diffuseSD.mtl.setActiveLobes(sd.mtl.getActiveLobes() & (uint)LobeType::DiffuseReflection);
        specularSD.mtl.setActiveLobes(sd.mtl.getActiveLobes() & (uint)LobeType::SpecularReflection);
        let dm=gScene.materials.getMaterialInstance(diffuseSD,ExplicitLodTextureSampler(0.f),primaryMaterialHints());
        let sm=gScene.materials.getMaterialInstance(specularSD,ExplicitLodTextureSampler(0.f),primaryMaterialHints());
        SampleGenerator sg=SampleGenerator(pixel,gFrameCount ^ 0x20000000u);
        float phase=sampleNext1D(sg)*2.f*M_PI;
        float factor=gHalfResolutionGather ? 2.f : 1.f;
        float2 q=(float2(pixel)-float2(gGatherOffset))/factor;
        // Evaluate samples at this full-resolution pixel, rather than interpolate
        // already shaded coarse pixels. Spiral neighbors follow the Lumen layout.
        uint integrationSamples=gRestirFullResolution ? gRestirIntegrateSamples : 1u;
        for (uint i=0;i<integrationSamples;i++)
        {
            float angle=phase+float(i)*2.39996323f;
            float radius=i==0 ? 0.f : pow(float(i),.666f) * gRestirIntegrateRadius * factor * (4.f/float(gRestirIntegrateSamples));
            int2 c=gRestirFullResolution ? int2(round(q+radius*float2(cos(angle),sin(angle)))) : int2(dispatchPixel);
            if (any(c<0)||any(c>=int2(gRestirDim))) continue;
            GatherReservoir r=gReservoirInput[reservoirIndex(uint2(c))];
            float depth=length(sd.posW-gScene.camera.getPosition());
            if (!compatibleSurface(sd.posW,sd.frame.N,depth,r)) continue;
            float plane=dot(sd.posW-r.originM.xyz,sd.frame.N)/max(depth,.01f);
            float w=exp2(-100000.f*plane*plane);
            total+=w; accepted++;
            float j=reconnectJacobian(r,sd.posW,sd.frame.N);
            if (j<=0.f || !reservoirVisible(r,sd)) continue;
            float3 direction=reservoirDirection(r,sd.posW);
            float3 lighting=r.radiance.xyz * r.normalW.w * j * w;
            if (gGatherDiffuse && (lobes & (uint)LobeType::DiffuseReflection)!=0)
                diffuse+=finiteRadiance(dm.eval(diffuseSD,direction,sg),0u)*lighting;
            if (gGatherSpecular && !sharpSpecular && (lobes & (uint)LobeType::SpecularReflection)!=0)
                specular+=finiteRadiance(sm.eval(specularSD,direction,sg),0u)*lighting;
            distance+=w*(r.hit.w>0.f ? length(r.hit.xyz-sd.posW) : 65504.f);
        }
        if (total>1e-8f) { diffuse/=total; specular/=total; distance/=total; }
        else
        {
            // Disoccluded thin geometry may have no compatible coarse sample.
            // Trace this pixel rather than fill it with a probe or a black hole.
            if (gGatherDiffuse) diffuse=gatherReflection(sd,(uint)LobeType::DiffuseReflection,
                UnpackDDGIVolumeDescGPU(DDGIVolumes[0]),sg,distance);
            sharpSpecular=true;
        }
        if (gGatherSpecular && sharpSpecular)
            specular=gatherReflection(sd,(uint)LobeType::SpecularReflection | (uint)LobeType::DeltaReflection,
                UnpackDDGIVolumeDescGPU(DDGIVolumes[0]),sg,specDistance);
        else specDistance=distance;
    }
    diffuse=finiteRadiance(diffuse*gIntensity,3u); specular=finiteRadiance(specular*gIntensity,3u);
    gOutputColor[pixel]=float4(gOutputColor[pixel].rgb+diffuse+specular,1.f);
#if OUTPUT_GATHER_DIFFUSE
    gOutputGatherDiffuse[pixel]=float4(diffuse,1.f);
#endif
#if OUTPUT_GATHER_SPECULAR
    gOutputGatherSpecular[pixel]=float4(specular,1.f);
#endif
#if OUTPUT_INDIRECT
    gOutputIndirect[pixel]=float4(diffuse+specular,1.f);
#endif
#if OUTPUT_DIFFUSERADIANCEHITDIST && OUTPUT_DIFFUSEREFLECTANCE
    gDiffuseRadianceHitDist[outputPixel]=float4(diffuse/max(gDiffuseReflectance[pixel].rgb,float3(1e-4f)),distance);
#endif
#if OUTPUT_SPECULARRADIANCEHITDIST && OUTPUT_SPECULARREFLECTANCE
    gSpecularRadianceHitDist[outputPixel]=float4(specular/max(gSpecularReflectance[pixel].rgb,float3(1e-4f)),specDistance);
#endif
#if OUTPUT_RESTIR_DEBUG
    uint index=reservoirIndex(min(pixel/(gHalfResolutionGather ? 2u:1u),gRestirDim-1u));
    gRestirDebug[pixel]=float4(gReservoirTemporal[index].originM.w,gReservoirInput[index].originM.w,float(accepted),1.f);
#endif
}
#endif
