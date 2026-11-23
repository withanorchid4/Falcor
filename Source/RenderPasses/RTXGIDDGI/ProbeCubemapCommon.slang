// Shared, exact inverse conventions for raster projection and direction lookup.
float3 cubeForward(uint f) { return f==0?float3(1,0,0):f==1?float3(-1,0,0):f==2?float3(0,1,0):f==3?float3(0,-1,0):f==4?float3(0,0,1):float3(0,0,-1); }
float3 cubeUp(uint f) { return f==2?float3(0,0,-1):f==3?float3(0,0,1):float3(0,1,0); }
uint cubeFace(float3 d) { float3 a=abs(d);return a.x>=a.y&&a.x>=a.z?(d.x>=0?0:1):a.y>=a.z?(d.y>=0?2:3):(d.z>=0?4:5); }
float2 cubeUV(float3 d,uint f) { float3 F=cubeForward(f),U=cubeUp(f),R=cross(F,U);return float2(dot(d,R),-dot(d,U))/dot(d,F)*.5f+.5f; }
