import Environment;

Texture2D<float4> gSource;
RWTexture2D<float4> gDestination;

[numthreads(8, 8, 1)]
void main(uint3 index : SV_DispatchThreadID)
{
    uint width, height;
    gDestination.GetDimensions(width, height);
    if (index.x >= width || index.y >= height) return;

    // Read unfiltered source texels so one invalid HDR value cannot contaminate
    // its neighbors or every mip of the environment importance distribution.
    gDestination[index.xy] = float4(sanitizeRTXDIEnvironmentRadiance(gSource[index.xy].rgb), 1.f);
}
