// Build a finite, nonnegative importance-sampling source without changing the scene asset.
Texture2D<float4> gSource;
RWTexture2D<float4> gDestination;

[numthreads(8, 8, 1)]
void main(uint3 index : SV_DispatchThreadID)
{
    uint width, height;
    gDestination.GetDimensions(width, height);
    if (index.x >= width || index.y >= height) return;
    float3 value = gSource[index.xy].rgb;
    value = float3(isfinite(value.x) ? max(value.x, 0.f) : 0.f,
                   isfinite(value.y) ? max(value.y, 0.f) : 0.f,
                   isfinite(value.z) ? max(value.z, 0.f) : 0.f);
    gDestination[index.xy] = float4(value, 1.f);
}
