#include "RTXGIConfig.slang"
#include "RTXGI/rtxgi-sdk/shaders/ddgi/Irradiance.hlsl"
#include "ProbeCubemapCommon.slang"
import Scene.Raster;
StructuredBuffer<DDGIVolumeDescGPUPacked> DDGIVolumes;
Texture2DArray<float4> gProbeData;
cbuffer CaptureCB { uint gStart; uint gCount; uint gTotal; float gNear; float gFar; }
struct V { float3 p:TEXCOORD0; nointerpolation uint inst:TEXCOORD1; };
struct G { float4 h:SV_Position; float3 bary:TEXCOORD0; nointerpolation uint inst:TEXCOORD1; nointerpolation uint prim:TEXCOORD2; uint layer:SV_RenderTargetArrayIndex; };
V vsMain(VSIn i) { V o;o.inst=i.instanceID;GeometryInstanceID id={i.instanceID};o.p=mul(gScene.getWorldMatrix(id),float4(i.pos,1)).xyz;return o; }
[instance(32)]
[maxvertexcount(18)]
void gsMain(triangle V v[3],uint prim:SV_PrimitiveID,uint slot:SV_GSInstanceID,inout TriangleStream<G> stream)
{
 if(slot>=gCount)return;
 DDGIVolumeDescGPU volume=UnpackDDGIVolumeDescGPU(DDGIVolumes[0]);
 uint index=(gStart+slot)%gTotal;int3 coord=DDGIGetProbeCoords(index,volume);
 float3 origin=DDGIGetProbeWorldPosition(coord,volume,gProbeData);
 for(uint face=0;face<6;face++) {
  float3 F=cubeForward(face),U=cubeUp(face),R=cross(F,U);
  float3 p[3];float4 h[3];
  for(uint j=0;j<3;j++){p[j]=v[j].p-origin;float z=dot(p[j],F);h[j]=float4(dot(p[j],R),dot(p[j],U),gNear*(gFar-z)/(gFar-gNear),z);} // Reversed-Z.
  // Coarse triangle frustum rejection before emitting geometry.
  if(all(float3(h[0].w,h[1].w,h[2].w)<gNear))continue;
  if(all(float3(h[0].x-h[0].w,h[1].x-h[1].w,h[2].x-h[2].w)>0)||all(float3(-h[0].x-h[0].w,-h[1].x-h[1].w,-h[2].x-h[2].w)>0))continue;
  if(all(float3(h[0].y-h[0].w,h[1].y-h[1].w,h[2].y-h[2].w)>0)||all(float3(-h[0].y-h[0].w,-h[1].y-h[1].w,-h[2].y-h[2].w)>0))continue;
  for(uint j=0;j<3;j++){G o;o.h=h[j];o.inst=v[j].inst;o.prim=prim;o.bary=j==0?float3(1,0,0):j==1?float3(0,1,0):float3(0,0,1);o.layer=slot*6+face;stream.Append(o);}stream.RestartStrip();
 }
}
uint4 psMain(G i):SV_Target0
{
 GeometryInstanceID id={i.inst};uint material=gScene.getMaterialID(id);
 TriangleHit hit;hit.instanceID=id;hit.primitiveIndex=i.prim;hit.barycentrics=i.bary.yz;
 if(gScene.materials.getMaterialHeader(material).getAlphaMode()==AlphaMode::Mask){VertexData v=gScene.getVertexData(hit);if(gScene.materials.alphaTest(v,material,0.f))discard;}
 PackedHitInfo packed=hit.pack();
#if HIT_INFO_USE_COMPRESSION
 return uint4(packed,0,0);
#else
 return packed;
#endif
}
