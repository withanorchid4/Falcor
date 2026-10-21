// Environment input validation belongs to the Falcor adapter, not the RTXDI SDK.
float3 sanitizeRTXDIEnvironmentRadiance(float3 value)
{
    return float3(isfinite(value.x) ? max(value.x, 0.f) : 0.f,
                  isfinite(value.y) ? max(value.y, 0.f) : 0.f,
                  isfinite(value.z) ? max(value.z, 0.f) : 0.f);
}

float3 evalRTXDIEnvironment(Texture2D<float4> environment, SamplerState environmentSampler, float2 uv, float3 intensity)
{
    // The texture has already been sanitized before filtering. Keep valid
    // neighboring texels, and also guard multiplication by the scene intensity.
    return sanitizeRTXDIEnvironmentRadiance(environment.SampleLevel(environmentSampler, uv, 0.f).rgb * intensity);
}
