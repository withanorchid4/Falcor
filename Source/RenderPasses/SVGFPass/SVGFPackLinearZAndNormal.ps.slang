/***************************************************************************
 # Copyright (c) 2015-23, NVIDIA CORPORATION. All rights reserved.
 #
 # Redistribution and use in source and binary forms, with or without
 # modification, are permitted provided that the following conditions
 # are met:
 #  * Redistributions of source code must retain the above copyright
 #    notice, this list of conditions and the following disclaimer.
 #  * Redistributions in binary form must reproduce the above copyright
 #    notice, this list of conditions and the following disclaimer in the
 #    documentation and/or other materials provided with the distribution.
 #  * Neither the name of NVIDIA CORPORATION nor the names of its
 #    contributors may be used to endorse or promote products derived
 #    from this software without specific prior written permission.
 #
 # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS "AS IS" AND ANY
 # EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 # IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 # PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 # CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 # EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 # PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 # PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 # OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 # (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 # OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 **************************************************************************/
import Utils.Math.MathHelpers;
import SVGFCommon;

cbuffer PerImageCB
{
    Texture2D gLinearZ;
    Texture2D gNormal;
    Texture2D gWorldPosition;
};

struct PS_OUT
{
    float4 depthNormal : SV_TARGET0;
    float2 posNormalFwidth : SV_TARGET1;
};

PS_OUT main(FullScreenPassVsOut vsOut)
{
    float4 fragCoord = vsOut.posH;
    const int2 ipos = int2(fragCoord.xy);

    const float3 normal = gNormal[ipos].xyz;
    const bool validSurface = dot(normal, normal) > 0.f;
    const float2 nPacked = ndir_to_oct_snorm(validSurface ? normal : float3(0, 0, 1));
    PS_OUT result;
    result.depthNormal = float4(validSurface ? gLinearZ[ipos].xy : float2(-1, 0), nPacked.x, nPacked.y);
    result.posNormalFwidth = float2(length(fwidth(gWorldPosition[ipos].xyz)), length(fwidth(normal)));
    return result;
}
