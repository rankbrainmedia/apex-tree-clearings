#!/usr/bin/env python
"""Step 2: 10 m baseline forest mask on the Sentinel-2 grid.

- canopy fraction per 10 m cell = canopy 1 m pixels / valid 1 m pixels, from the NAIP 2022 canopy mask
- forest_2022 = (valid 1 m pixels >= 50) and (canopy fraction >= 0.5)
- in-boundary = the 10 m cell centre falls inside the dissolved Apex boundary
Writes WORK/baseline.npz and OUT/baseline_forest_10m.tif (1 forest, 0 not, 255 outside).
"""
import os
import numpy as np, rasterio, geopandas as gpd
from rasterio.features import rasterize
from affine import Affine
import config as C

T10 = Affine(10, 0, C.X0, 0, -10, C.Y1)


def main():
    with rasterio.open(C.NAIP_CANOPY_2022) as r:
        a = r.read(1); t = r.transform
    # the 1 m mask starts a few metres inside the 10 m grid; pad it onto the grid
    dx = int(round(t.c - C.X0)); dy = int(round(C.Y1 - t.f))
    big = np.full((C.H * 10, C.W * 10), 255, np.uint8)
    big[dy:dy + a.shape[0], dx:dx + a.shape[1]] = a
    blk = big.reshape(C.H, 10, C.W, 10)
    valid = (blk != 255).sum((1, 3))
    can = (blk == 1).sum((1, 3))
    frac = np.where(valid > 0, can / np.maximum(valid, 1), np.nan).astype(np.float32)
    forest = (valid >= C.MIN_VALID_1M) & (frac >= C.FOREST_FRAC)

    b = gpd.read_file(C.BOUNDARY).to_crs(C.EPSG)
    inb = rasterize([(g, 1) for g in b.geometry], out_shape=(C.H, C.W), transform=T10,
                    all_touched=False).astype(bool)
    forest &= inb
    np.savez_compressed(os.path.join(C.WORK, "baseline.npz"), frac=frac, forest=forest, inb=inb)
    prof = dict(driver="GTiff", width=C.W, height=C.H, count=1, dtype="uint8", crs=f"EPSG:{C.EPSG}",
                transform=T10, compress="lzw", nodata=255)
    with rasterio.open(os.path.join(C.OUT, "baseline_forest_10m.tif"), "w", **prof) as d:
        d.write(np.where(inb, forest.astype(np.uint8), 255), 1)
    print(f"in-boundary {inb.sum() * 100 / C.M2_PER_AC:.1f} ac, baseline forest "
          f"{forest.sum() * 100 / C.M2_PER_AC:.1f} ac ({100 * forest.sum() / inb.sum():.1f}%)")


if __name__ == "__main__":
    main()
