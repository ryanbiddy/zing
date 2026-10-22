"""D65 sRGB -> CIELAB and the CIEDE2000 equations (kL=kC=kH=1).

Equation reference: Sharma, Wu, Dalal (2005), doi:10.1002/col.20070.
This implementation is tested against the paper's published test pairs.
"""

from . import require_numpy

np = require_numpy()


def rgb_array(rgb):
    value = np.asarray(rgb, dtype=np.float64)
    if value.ndim == 0 or value.size == 0 or value.shape[-1] != 3 or not np.isfinite(value).all():
        raise ValueError("RGB must be a nonempty finite array with three channels")
    if np.min(value) < 0 or np.max(value) > 1:
        raise ValueError("RGB values must be normalized to [0, 1]")
    return value


def linearize(rgb):
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def encode(linear):
    linear = np.maximum(linear, 0.0)
    return np.where(linear <= 0.0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - 0.055)


def rgb_to_lab(rgb):
    linear = linearize(rgb_array(rgb))
    xyz = linear @ np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]).T
    xyz /= [0.95047, 1.0, 1.08883]
    d = 6 / 29
    f = np.where(xyz > d ** 3, np.cbrt(xyz), xyz / (3 * d * d) + 4 / 29)
    return np.stack((116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])), axis=-1)


def delta_e_2000(lab1, lab2):
    """Vectorized perceptual difference; inputs have last dimension L*,a*,b*."""
    l1, a1, b1 = np.moveaxis(np.asarray(lab1, dtype=float), -1, 0)
    l2, a2, b2 = np.moveaxis(np.asarray(lab2, dtype=float), -1, 0)
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cbar = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7)))
    ap1, ap2 = (1 + g) * a1, (1 + g) * a2
    cp1, cp2 = np.hypot(ap1, b1), np.hypot(ap2, b2)
    hp1 = np.mod(np.degrees(np.arctan2(b1, ap1)), 360)
    hp2 = np.mod(np.degrees(np.arctan2(b2, ap2)), 360)
    zero = cp1 * cp2 == 0
    dh = hp2 - hp1
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(zero, 0, dh)
    dl, dc = l2 - l1, cp2 - cp1
    d_h = 2 * np.sqrt(cp1 * cp2) * np.sin(np.radians(dh / 2))
    lb, cb = (l1 + l2) / 2, (cp1 + cp2) / 2
    hsum = hp1 + hp2
    hb = np.where(np.abs(hp1 - hp2) <= 180, hsum / 2,
                  np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2))
    hb = np.where(zero, hsum, hb)
    rad = np.radians
    t = (1 - 0.17 * np.cos(rad(hb - 30)) + 0.24 * np.cos(rad(2 * hb))
         + 0.32 * np.cos(rad(3 * hb + 6)) - 0.20 * np.cos(rad(4 * hb - 63)))
    sl = 1 + 0.015 * (lb - 50) ** 2 / np.sqrt(20 + (lb - 50) ** 2)
    sc, sh = 1 + 0.045 * cb, 1 + 0.015 * cb * t
    rt = (-2 * np.sqrt(cb ** 7 / (cb ** 7 + 25 ** 7))
          * np.sin(rad(60 * np.exp(-((hb - 275) / 25) ** 2))))
    return np.sqrt(np.maximum(0, (dl / sl) ** 2 + (dc / sc) ** 2
                              + (d_h / sh) ** 2 + rt * (dc / sc) * (d_h / sh)))
