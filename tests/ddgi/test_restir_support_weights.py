"""Exact finite-domain check: receiver {a,b}, neighbor {b,c}; no Monte Carlo noise."""
from itertools import product
f={'a':1.,'b':3.};source_domains=[{'a','b'},{'b','c'}]
def expected(corrected):
 total=0.
 for a,b in product(['a','b'],['b','c']):
  candidates=[a,b];weights=[2.,2. if b in f else 0.];s=sum(weights)
  legacy_count=1+int(b in f)
  for x,w in zip(candidates,weights):
   if w==0:continue
   denominator=sum(x in domain for domain in source_domains) if corrected else legacy_count
   total+=.25*(w/s)*(s/denominator)*f[x]
 return total
assert abs(expected(True)-4.)<1e-12
assert abs(expected(False)-4.5)<1e-12
print('Exact integral=4; sample-dependent rejection=4.5; source-support correction=4')

# A chosen source failing the reverse support test must zero the numerator.
# This inconsistent-support state can occur with visibility/geometry tolerances.
def normalized_weight(total, p, source_p, source_p_sum):
 return total*source_p/(p*source_p_sum) if p*source_p_sum>0 else 0.
assert normalized_weight(20.,1.,1.,20.)==1.
assert normalized_weight(20.,1.,0.,1.)==0.
assert normalized_weight(20.,1.,1.,1.)==20. # Fresh source selected; do not blanket-clamp.
print('Selected-source numerator: valid support W=1; invalid selected source W=0.')
