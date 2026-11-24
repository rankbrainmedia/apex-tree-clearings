#!/usr/bin/env python
"""Step 1: query the Microsoft Planetary Computer STAC for Sentinel-2 L2A scenes over Apex.

Writes WORK/items.json (raw STAC item dicts). No API key is needed.
The query is: collection sentinel-2-l2a, bbox = bounds of the Apex boundary in EPSG:4326,
datetime DATE_START..DATE_END, then keep MGRS tile 17SPV only.
For release v1.0 this returned 802 items (663 unique datatakes after de-duplication in step 3).
"""
import json, os
import geopandas as gpd
import pystac_client
import config as C


def main():
    bb = [float(v) for v in gpd.read_file(C.BOUNDARY).to_crs(4326).total_bounds]
    cat = pystac_client.Client.open(C.STAC_URL)
    items = cat.search(collections=[C.COLLECTION], bbox=bb,
                       datetime=f"{C.DATE_START}/{C.DATE_END}").items()
    out = [i.to_dict() for i in items if i.properties.get("s2:mgrs_tile") == C.MGRS_TILE]
    json.dump(out, open(os.path.join(C.WORK, "items.json"), "w"))
    print(f"bbox {bb}; {len(out)} items on tile {C.MGRS_TILE} -> {C.WORK}/items.json")


if __name__ == "__main__":
    main()
