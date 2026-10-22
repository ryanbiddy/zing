"""CIELAB D65 palette centroids to display sRGB swatches, clipped to gamut."""


def lab_hex(lab):
    light, a, b = lab
    fy = (light+16)/116
    delta = 6/29
    def inverse(v):
        return v**3 if v > delta else 3*delta*delta*(v-4/29)
    x, y, z = inverse(fy+a/500)*.95047, inverse(fy), inverse(fy-b/200)*1.08883
    rgb = (3.2404542*x-1.5371385*y-.4985314*z,
           -.969266*x+1.8760108*y+.041556*z,
           .0556434*x-.2040259*y+1.0572252*z)
    def encode(v):
        return 12.92*v if v <= .0031308 else 1.055*v**(1/2.4)-.055
    return "#"+"".join(f"{max(0, min(255, round(encode(v)*255))):02x}" for v in rgb)
