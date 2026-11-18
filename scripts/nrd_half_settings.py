"""RELAX presets for the opaque diffuse half-resolution final gather experiment."""
LEGACY = {
    'inputSampleOffset': [0.,0.],
    'diffusePrepassBlurRadius':16., 'atrousIterationNum':6,
    'diffuseMaxAccumulatedFrameNum':31, 'diffuseMaxFastAccumulatedFrameNum':2,
    'historyClampingColorBoxSigmaScale':2.,
}
TUNED = {
    # The input samples full-resolution pixels (2*x,2*y), not 2x2 block centers.
    'inputSampleOffset':[-.25,-.25],
    'diffusePrepassBlurRadius':0., 'atrousIterationNum':2,
    'diffuseMaxAccumulatedFrameNum':31, 'diffuseMaxFastAccumulatedFrameNum':8,
    'historyClampingColorBoxSigmaScale':3.,
}
