"""Shared settings for the Apex, NC Sentinel-2 forest-clearing pipeline (release v1.0).

Every path is relative to this folder unless you override it with an environment variable:
  APEX_WORK   working/cache folder (default ./work). The composites take about 600 MB.
  APEX_OUT    output folder for the release products (default ./out)
"""
import os

CODE = os.path.dirname(os.path.abspath(__file__))
INPUTS = os.path.join(CODE, "inputs")
WORK = os.environ.get("APEX_WORK", os.path.join(CODE, "work"))
OUT = os.environ.get("APEX_OUT", os.path.join(CODE, "out"))
os.makedirs(WORK, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

# ---- inputs (see inputs/README.md for provenance) ----
NAIP_CANOPY_2022 = os.path.join(INPUTS, "canopy_2022_naip.tif")   # 1 m, 1 = canopy, 0 = not, 255 = nodata
BOUNDARY = os.path.join(INPUTS, "boundary.gpkg")                  # Apex Corporate Limits + ETJ, dissolved
NAIP_LOSS_2020_2022 = os.path.join(INPUTS, "loss_2020_2022_naip.gpkg")  # validation only

# ---- Sentinel-2 query ----
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
MGRS_TILE = "17SPV"
DATE_START = "2022-07-01T00:00:00Z"
DATE_END = "2026-10-24T23:59:59Z"      # data cut-off for release v1.0

# ---- analysis grid: 10 m, EPSG:32617, aligned to the native S2 17SPV pixel grid ----
EPSG = 32617
X0, X1, Y0, Y1 = 683800, 698840, 3948740, 3961460
W, H = (X1 - X0) // 10, (Y1 - Y0) // 10     # 1504 x 1272
M2_PER_AC = 4046.8564
MIN_PX = 41                                  # ceil(4046.86 m2 / 100 m2) = 1 acre

# ---- clear-pixel masking ----
KEEP_SCL = (4, 5, 6)            # vegetation, bare soil, water
CLOUD_SCL = (3, 8, 9, 10)       # cloud shadow, cloud medium, cloud high, thin cirrus
CLOUD_DILATE = 2                # SCL (20 m) pixels -> 40 m buffer
MIN_SCENE_CLEAR = 0.01          # skip a scene if <1% of the AOI window is clear
MIN_CLEAR_OF_COVERED = 0.20     # skip a scene if <20% of its data-covered AOI part is clear
BOA_OFFSET = -1000.0            # processing baseline >= 04.00

# ---- baseline forest ----
FOREST_FRAC = 0.5               # 10 m cell is forest if >= 50% of valid 1 m pixels are canopy
MIN_VALID_1M = 50               # ... and it has >= 50 valid 1 m pixels

# ---- detection defaults ----
T_NDVI = 0.50
T_NBR = 0.65
MIN_OBS = 2
LEAFON_NBR_P1 = 0.75

# ---- control sites (300 m radius). Coordinates are the OpenStreetMap feature points
#      returned by Nominatim on 2026-10-27; OSM ids listed so anyone can check them. ----
CONTROL_RADIUS_M = 300
CONTROLS = [
    # name, lon, lat, source
    ("Apex Community Park", -78.8236380, 35.7513576, "OSM relation 8264995"),
    ("Apex Nature Park", -78.9074603, 35.7202838, "OSM relation 8257028"),
    ("Kelly Road Park", -78.8938889, 35.7316594, "OSM way 33111540"),
]
