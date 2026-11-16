// Optional ALU/divergence experiment. Each type has six dependent uint operations
// per iteration (two shifts, two XORs, one multiply, one add), in distinct orders.
// Runtime seed/count and the caller's checksum UAV store prevent constant folding
// and dead-code elimination. This does not model texture or BSDF cost.
#ifndef FALCOR_WRC_STRESS
#define FALCOR_WRC_STRESS
#ifndef WRC_STRESS_ENABLED
#define WRC_STRESS_ENABLED 0
#endif
uint wrcStress(uint x, uint type, uint iterations)
{
    [branch]
    switch (type)
    {
    case 0:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x ^= x >> 5; x *= 0x7feb352du; x ^= x << 11; x += 0x9e3779b9u; }
        break;
    case 1:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x ^= x << 7; x += 0x85ebca6bu; x ^= x >> 13; x *= 0x846ca68bu; }
        break;
    case 2:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x *= 0x27d4eb2du; x ^= x >> 11; x += 0xc2b2ae35u; x ^= x << 9; }
        break;
    case 3:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x += 0x165667b1u; x ^= x << 13; x *= 0x9e3779b9u; x ^= x >> 7; }
        break;
    case 4:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x ^= x >> 17; x += 0xd3a2646du; x ^= x >> 5; x *= 0x85ebca6bu; }
        break;
    case 5:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x ^= x << 9; x *= 0xc2b2ae35u; x ^= x << 3; x += 0x27d4eb2fu; }
        break;
    case 6:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x *= 0x165667b1u; x ^= x << 15; x += 0x846ca68bu; x ^= x >> 9; }
        break;
    case 7:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x += 0x7feb352du; x ^= x >> 3; x *= 0xd3a2646du; x ^= x << 17; }
        break;
    case 8:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x ^= x >> 13; x ^= x << 5; x *= 0x846ca68bu; x += 0x165667b1u; }
        break;
    case 9:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x ^= x << 11; x ^= x >> 17; x += 0x9e3779b9u; x *= 0x27d4eb2du; }
        break;
    default:
        [loop] for (uint i = 0; i < iterations; ++i)
        { x *= 0x85ebca6bu; x += 0xc2b2ae35u; x ^= x << 7; x ^= x >> 15; }
        break;
    }
    return x;
}
#endif
