"""GeoTIFF reading, WGS84 overlay prep, click sampling, and water sample raster."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
import streamlit as st

# Discrete classes in Training_raster.tif (ArcGIS Reclassify 1-4).
CLASS_RISK = {
    1: "clean",
    2: "slightly_contaminated",
    3: "moderate",
    4: "heavy",
}

RISK_LABELS = {
    "clean": "Clean",
    "slightly_contaminated": "Slightly contaminated",
    "moderate": "Moderate",
    "heavy": "Heavy contamination",
}

RISK_COLORS = {
    "clean": "#4CAF50",
    "slightly_contaminated": "#FFEB3B",
    "moderate": "#FF9800",
    "heavy": "#F44336",
}

# Fallback if a continuous concentration raster is uploaded later.
CONTINUOUS_THRESHOLDS = (
    ("clean", 0.5),
    ("slightly_contaminated", 1.0),
    ("moderate", 2.0),
)

RISK_RGBA = {
    "clean": (76, 175, 80, 255),
    "slightly_contaminated": (255, 235, 59, 255),
    "moderate": (255, 152, 0, 255),
    "heavy": (244, 67, 54, 255),
}

WATER_SAMPLE_TAG = "SAMPLE_GENERATED_PLACEHOLDER_V2"
TARGET_CRS = CRS.from_epsg(4326)


def get_risk_category(value: float, classified: bool = True) -> str:
    """Map a pixel value to the four-tier risk scheme."""
    if classified and int(value) in CLASS_RISK:
        return CLASS_RISK[int(round(float(value)))]
    for name, upper in CONTINUOUS_THRESHOLDS:
        if value <= upper:
            return name
    return "heavy"


def _is_classified_band(band: np.ndarray, nodata: Optional[float]) -> bool:
    data = band.astype("float64")
    if nodata is not None:
        data = data[data != nodata]
    data = data[np.isfinite(data)]
    if data.size == 0:
        return False
    unique = np.unique(data)
    if unique.size > 12:
        return False
    rounded = np.round(unique)
    return np.allclose(unique, rounded) and set(rounded.astype(int)).issubset({1, 2, 3, 4})


def _nodata_mask(band: np.ndarray, nodata: Optional[float]) -> np.ndarray:
    mask = ~np.isfinite(band)
    if nodata is not None:
        mask |= band == nodata
    return mask


def apply_color_classification(band: np.ndarray, nodata: Optional[float] = None) -> np.ndarray:
    """Convert a raster band to RGBA using the 4-tier cartographic scheme."""
    height, width = band.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    invalid = _nodata_mask(band, nodata)
    classified = _is_classified_band(band, nodata)

    if classified:
        classes = np.zeros_like(band, dtype=np.int16)
        valid = ~invalid
        classes[valid] = np.rint(band[valid]).astype(np.int16)
        for code, risk in CLASS_RISK.items():
            rgba[classes == code] = RISK_RGBA[risk]
    else:
        clean = (~invalid) & (band <= CONTINUOUS_THRESHOLDS[0][1])
        slight = (~invalid) & (band > CONTINUOUS_THRESHOLDS[0][1]) & (band <= CONTINUOUS_THRESHOLDS[1][1])
        moderate = (~invalid) & (band > CONTINUOUS_THRESHOLDS[1][1]) & (band <= CONTINUOUS_THRESHOLDS[2][1])
        heavy = (~invalid) & (band > CONTINUOUS_THRESHOLDS[2][1])
        rgba[clean] = RISK_RGBA["clean"]
        rgba[slight] = RISK_RGBA["slightly_contaminated"]
        rgba[moderate] = RISK_RGBA["moderate"]
        rgba[heavy] = RISK_RGBA["heavy"]

    rgba[invalid, 3] = 0
    return rgba


@st.cache_resource(show_spinner=False)
def get_raster_src(raster_path: str):
    """Keep the GeoTIFF handle open so map clicks do not re-read the file."""
    return rasterio.open(raster_path)


def _wgs84_bounds_from_src(src) -> list:
    transformer = Transformer.from_crs(src.crs, TARGET_CRS, always_xy=True)
    xs = [src.bounds.left, src.bounds.right, src.bounds.left, src.bounds.right]
    ys = [src.bounds.bottom, src.bounds.bottom, src.bounds.top, src.bounds.top]
    lons, lats = transformer.transform(xs, ys)
    return [[float(min(lats)), float(min(lons))], [float(max(lats)), float(max(lons))]]


@st.cache_data(show_spinner=False, ttl=3600)
def prepare_raster_overlay(raster_path: str, max_dim: int = 800) -> Tuple[Optional[np.ndarray], Optional[list], Dict[str, Any]]:
    """Reproject (if needed) to EPSG:4326 and return RGBA + Folium bounds."""
    try:
        with rasterio.open(raster_path) as src:
            metadata = {
                "crs": str(src.crs),
                "nodata": src.nodata,
                "width": src.width,
                "height": src.height,
                "bounds": {
                    "left": float(src.bounds.left),
                    "bottom": float(src.bounds.bottom),
                    "right": float(src.bounds.right),
                    "top": float(src.bounds.top),
                },
                "media": Path(raster_path).stem,
                "tags": dict(src.tags()),
            }
            if src.crs is None:
                metadata["error"] = "Raster has no CRS defined"
                return None, None, metadata

            band = src.read(1)
            src_crs = CRS.from_user_input(src.crs)
            src_transform = src.transform
            src_bounds = src.bounds
            nodata = src.nodata
            src_width, src_height = src.width, src.height

        if src_crs == TARGET_CRS:
            bounds = [[src_bounds.bottom, src_bounds.left], [src_bounds.top, src_bounds.right]]
            rgba_image = apply_color_classification(band, nodata)
            metadata["overlay_width"] = src_width
            metadata["overlay_height"] = src_height
            return rgba_image, bounds, metadata

        transform, width, height = calculate_default_transform(
            src_crs, TARGET_CRS, src_width, src_height, *src_bounds
        )
        if max(width, height) > max_dim:
            scale = max_dim / float(max(width, height))
            width = max(1, int(width * scale))
            height = max(1, int(height * scale))
            transform, width, height = calculate_default_transform(
                src_crs,
                TARGET_CRS,
                src_width,
                src_height,
                *src_bounds,
                dst_width=width,
                dst_height=height,
            )

        reprojected = np.zeros((height, width), dtype=np.float32)
        reproject(
            source=band.astype("float32"),
            destination=reprojected,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=transform,
            dst_crs=TARGET_CRS,
            src_nodata=nodata,
            dst_nodata=np.nan,
            resampling=Resampling.nearest,
        )

        left, bottom, right, top = array_bounds(height, width, transform)
        bounds = [[float(bottom), float(left)], [float(top), float(right)]]
        rgba_image = apply_color_classification(reprojected, nodata=np.nan)
        metadata["overlay_width"] = width
        metadata["overlay_height"] = height
        metadata["wgs84_bounds"] = bounds
        return rgba_image, bounds, metadata
    except Exception as exc:
        return None, None, {"error": str(exc)}


def sample_raster_value(raster_path: str, lat: float, lon: float) -> Dict[str, Any]:
    """Sample native-CRS pixel value at a WGS84 click location."""
    try:
        src = get_raster_src(raster_path)
        if src.crs is None:
            return {"error": "Raster has no CRS defined"}

        transformer = Transformer.from_crs(TARGET_CRS, src.crs, always_xy=True)
        x, y = transformer.transform(lon, lat)

        if not (src.bounds.left <= x <= src.bounds.right and src.bounds.bottom <= y <= src.bounds.top):
            return {"error": "Point outside raster extent"}

        value = next(src.sample([(x, y)]))[0]
        if src.nodata is not None and value == src.nodata:
            return {"error": "No prediction at this location"}
        if not np.isfinite(value):
            return {"error": "No prediction at this location"}

        classified = src.dtypes[0] in ("uint8", "int8", "uint16", "int16") and int(round(float(value))) in CLASS_RISK
        risk_category = get_risk_category(float(value), classified=classified)
        return {
            "value": float(value),
            "class_code": int(round(float(value))) if classified else None,
            "risk_category": risk_category,
            "risk_label": RISK_LABELS[risk_category],
            "color": RISK_COLORS[risk_category],
            "coordinates": {"lat": lat, "lon": lon},
            "raster_crs": str(src.crs),
            "classified": classified,
        }
    except StopIteration:
        return {"error": "Point outside raster extent"}
    except Exception as exc:
        return {"error": str(exc)}


def is_sample_raster(raster_path: str) -> bool:
    try:
        src = get_raster_src(raster_path)
        status = src.tags().get("DATA_STATUS", "")
        return str(status).startswith("SAMPLE_GENERATED")
    except Exception:
        try:
            with rasterio.open(raster_path) as src:
                status = src.tags().get("DATA_STATUS", "")
            return str(status).startswith("SAMPLE_GENERATED")
        except Exception:
            return False


def _write_water_sample(soil_path: str, dest: Path) -> None:
    with rasterio.open(soil_path) as src:
        soil = src.read(1)
        profile = src.profile.copy()
        nodata = src.nodata if src.nodata is not None else 15
        height, width = soil.shape
        yy, xx = np.indices(soil.shape)

        field = (
            0.42
            + 0.28 * np.sin(xx / 95.0) * np.cos(yy / 70.0)
            + 0.32 * np.exp(-((xx - width * 0.32) ** 2 + (yy - height * 0.38) ** 2) / (2 * 110.0 ** 2))
            + 0.26 * np.exp(-((xx - width * 0.68) ** 2 + (yy - height * 0.62) ** 2) / (2 * 90.0 ** 2))
            - 0.18 * np.exp(-((xx - width * 0.18) ** 2 + (yy - height * 0.78) ** 2) / (2 * 80.0 ** 2))
        )
        classes = np.digitize(field, [0.28, 0.48, 0.70], right=True) + 1
        classes = classes.astype(np.uint8)
        invalid = _nodata_mask(soil, src.nodata)
        classes[invalid] = np.uint8(nodata)

        profile.update(dtype="uint8", count=1, nodata=int(nodata), compress="lzw")
        with rasterio.open(dest, "w", **profile) as dst:
            dst.write(classes, 1)
            dst.update_tags(
                DATA_STATUS=WATER_SAMPLE_TAG,
                DESCRIPTION="Placeholder water contamination classes. Replace this file with the real water prediction raster.",
            )


def ensure_water_sample_raster(soil_path: str, output_path: str) -> str:
    """
    Create a same-grid water prediction GeoTIFF filled with generated sample classes.

    Replace `data/Raster/Water_sample_raster.tif` with the real water raster when it
    is available. Existing files that are not tagged as sample placeholders are kept.
    """
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return str(dest)

    _write_water_sample(soil_path, dest)
    get_raster_src.clear()
    prepare_raster_overlay.clear()
    return str(dest)


def raster_map_center(raster_path: str) -> Tuple[float, float]:
    """Return (lat, lon) centre of the raster in WGS84."""
    src = get_raster_src(raster_path)
    bounds = _wgs84_bounds_from_src(src)
    lat = (bounds[0][0] + bounds[1][0]) / 2.0
    lon = (bounds[0][1] + bounds[1][1]) / 2.0
    return lat, lon
