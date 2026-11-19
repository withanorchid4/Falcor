cbuffer GatherPhase { uint2 gGatherOffset; };
Texture2D<float2> depth;
Texture2D<float4> normalRoughness, motion;
RWTexture2D<float2> halfDepth;
RWTexture2D<float4> halfNormalRoughness, halfMotion;

[numthreads(8,8,1)]
void prepare(uint3 tid : SV_DispatchThreadID)
{
    uint w,h; halfDepth.GetDimensions(w,h);
    uint2 p=tid.xy;
    if (any(p>=uint2(w,h))) return;
    halfDepth[p]=depth[2*p+gGatherOffset];
    halfNormalRoughness[p]=normalRoughness[2*p+gGatherOffset];
    halfMotion[p]=motion[2*p+gGatherOffset];
}

Texture2D<float4> normal, diffuse, specular, diffuseReflectance, specularReflectance, direct;
RWTexture2D<float4> color;
[numthreads(8,8,1)]
void resolve(uint3 tid : SV_DispatchThreadID)
{
    uint w,h,hw,hh; color.GetDimensions(w,h); diffuse.GetDimensions(hw,hh);
    uint2 p=tid.xy;
    if (any(p>=uint2(w,h))) return;
    // Full-resolution samples need no spatial reconstruction.
    // Negative direct alpha marks an opaque diagnostic overlay. Never add GI
    // over it or include its color in the coarse gather reconstruction.
    if (direct[p].a < 0.f) { color[p] = float4(direct[p].rgb, 1.f); return; }
    if (w == hw && h == hh)
    {
        color[p] = float4(direct[p].rgb + diffuse[p].rgb * diffuseReflectance[p].rgb
            + specular[p].rgb * specularReflectance[p].rgb, 1.f);
        return;
    }
    float3 n=normal[p].xyz;
    float z=depth[p].x;
    float3 d=0,s=0; float sum=0;
    if (dot(n,n)>.5f)
    {
        // Locate the current phase in full-resolution coordinates before filtering.
        float2 q=(float2(p)-float2(gGatherOffset))*.5f;
        int2 base=int2(floor(q));
        for (int y=-1;y<=2;y++) for (int x=-1;x<=2;x++)
        {
            int2 tap=base+int2(x,y);
            if (any(tap<0)||any(tap>=int2(hw,hh))) continue;
            uint2 source=min(uint2(tap)*2+gGatherOffset,uint2(w,h)-1u);
            float3 nt=normal[source].xyz;
            float normalWeight=pow(saturate(dot(n,nt)),32.f);
            float depthWeight=exp(-abs(depth[source].x-z)/max(.01f,.01f*abs(z)));
            float2 delta=float2(tap)-q;
            float weight=exp(-dot(delta,delta))*normalWeight*depthWeight;
            d+=weight*diffuse[tap].rgb;s+=weight*specular[tap].rgb;sum+=weight;
        }
    }
    float3 result=direct[p].rgb;
    if (sum>1e-8f) result+=(d*diffuseReflectance[p].rgb+s*specularReflectance[p].rgb)/sum;
    color[p]=float4(result,1);
}
