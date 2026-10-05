import base64
import gzip
import io
import json
import math
import struct
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import joblib
from branca.element import MacroElement, Template
import streamlit as st
from folium.plugins import Fullscreen, LocateControl, MousePosition
from folium.raster_layers import ImageOverlay
from PIL import Image
from shapely.geometry import Point
from streamlit_folium import st_folium

from utils.raster_processor import (
    get_raster_src,
    prepare_raster_overlay,
    prepare_water_overlay,
    raster_map_center,
    sample_raster_value,
)
from utils.styles import (
    get_custom_css,
    get_popup_html,
    get_sidebar_footer_html,
)

ROOT = Path(__file__).resolve().parent
SOIL_RASTER = ROOT / "data" / "Raster" / "Training_raster.tif"
WATER_RASTER = ROOT / "data" / "Raster" / "Training_raster_Water.tif"
LOGO_PATH = ROOT / "assets" / "logo.png"
UPLOAD_DIR = ROOT / "data" / "Raster" / "uploads"
VECTOR_DIR = ROOT / "data" / "vector"
WARDS_GEOJSON = VECTOR_DIR / "Wards.geojson"
CONSTITUENCIES_GEOJSON = VECTOR_DIR / "Constituencies.geojson"
COUNTY_GEOJSON = VECTOR_DIR / "KakamegaCounty.geojson"
SAMPLE_POINTS_DIR = VECTOR_DIR / "SamplePoints"
SOIL_SAMPLE_POINTS = SAMPLE_POINTS_DIR / "Training_data_Soil.shp"
WATER_SAMPLE_POINTS = SAMPLE_POINTS_DIR / "Training_data_Water.shp"
TABLE_DIR = ROOT / "data" / "tables"
SOIL_METALS_TABLE = TABLE_DIR / "dominant_metals_soil.csv.gz.b64"
WATER_METALS_TABLE = TABLE_DIR / "dominant_metals_water.csv.gz.b64"
METAL_LIMITS_TABLE = TABLE_DIR / "metal_limits.csv.gz.b64"
ADDITIONAL_DIR = ROOT / "data" / "additional_data"
SOIL_CONFUSION_IMAGE = ADDITIONAL_DIR / "WhatsApp Image 2026-10-04 at 1.29.10 AM.jpeg"
WATER_CONFUSION_IMAGE = ADDITIONAL_DIR / "WhatsApp Image 2026-10-04 at 1.28.47 AM.jpeg"
SOIL_CLASS_CHART = ADDITIONAL_DIR / "WhatsApp Image 2026-10-04 at 1.28.47 AM (1).jpeg"
WATER_CLASS_CHART = ADDITIONAL_DIR / "WhatsApp Image 2026-10-04 at 1.28.47 AM (2).jpeg"
WATER_RF_MODEL = ADDITIONAL_DIR / "water_contamination_rf_model.pkl"
WATER_FEATURE_META = ADDITIONAL_DIR / "water_contamination_features.pkl"

st.set_page_config(
    page_title="Kakamega Heavy Metal Risk Assessment",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS for single viewport and cursor behavior
st.markdown("""
<style>
    .main .block-container {
        padding-top: 0.3rem;
        padding-bottom: 0.3rem;
        max-width: 100%;
    }
    .stApp {
        min-height: 100vh;
        overflow-y: auto;
        overflow-x: hidden;
    }
    div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column"] {
        gap: 0.1rem !important;
    }
    /* Cursor behavior for map - crosshair over map, arrow outside raster overlay */
    .leaflet-container {
        cursor: default !important;
    }
    .leaflet-container .leaflet-overlay-pane {
        cursor: crosshair !important;
    }
    .leaflet-container .leaflet-tile-pane {
        cursor: grab !important;
    }
    .leaflet-container .leaflet-tile-pane:active {
        cursor: grabbing !important;
    }
    /* Hide scrollbars for single viewport */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    ::-webkit-scrollbar-track {
        background: #f1f1f1;
    }
    ::-webkit-scrollbar-thumb {
        background: #888;
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #555;
    }
    /* Reduce spacing for compact layout */
    .stMarkdown, .stCaption {
        margin-top: 0.1rem !important;
        margin-bottom: 0.1rem !important;
    }
    h1 {
        margin-top: 0.2rem !important;
        margin-bottom: 0.2rem !important;
    }
    p {
        margin-top: 0.1rem !important;
        margin-bottom: 0.1rem !important;
    }

</style>
""", unsafe_allow_html=True)


def _encode_png(rgba_image) -> str:
    img = Image.fromarray(rgba_image)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@st.cache_data(show_spinner=False)
def _admin_lookup_geojson(path_string: str, candidate_fields: tuple[str, ...]) -> dict:
    """Return a compact WGS84 GeoJSON used only for instant browser-side lookup."""
    path = Path(path_string)
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}

    try:
        gdf = gpd.read_file(path)
        if gdf.crs is not None and str(gdf.crs) != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")

        name_field = next((field for field in candidate_fields if field in gdf.columns), None)
        if name_field is None:
            return {"type": "FeatureCollection", "features": []}

        slim = gdf[[name_field, "geometry"]].copy()
        slim = slim.rename(columns={name_field: "lookup_name"})

        # The source ward GeoJSON is large. A small simplification keeps point
        # identification responsive without changing the displayed vector layers.
        slim["geometry"] = slim.geometry.simplify(0.0002, preserve_topology=True)
        return json.loads(slim.to_json())
    except Exception:
        return {"type": "FeatureCollection", "features": []}


@st.cache_data(show_spinner=False)
def get_county_wgs84_bounds() -> list:
    """Return Kakamega County bounds as [[south, west], [north, east]]."""
    gdf = gpd.read_file(COUNTY_GEOJSON)
    if gdf.crs is not None and str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = gdf.total_bounds
    return [[float(miny), float(minx)], [float(maxy), float(maxx)]]


def add_instant_raster_click(m: folium.Map, rgba_image, bounds, medium: str) -> None:
    """Identify raster and admin polygons fully in-browser without Streamlit reruns."""
    if rgba_image is None or bounds is None:
        return

    image_url = _encode_png(rgba_image)
    south, west = bounds[0]
    north, east = bounds[1]

    county_data = _admin_lookup_geojson(
        str(COUNTY_GEOJSON),
        ("ADM1_EN", "COUNTY", "County", "county", "NAME_1"),
    )
    constituency_data = _admin_lookup_geojson(
        str(CONSTITUENCIES_GEOJSON),
        ("ADM2_EN", "CONSTITUEN", "Constituency", "constituency", "NAME_2"),
    )
    ward_data = _admin_lookup_geojson(
        str(WARDS_GEOJSON),
        ("ward", "WARD", "Ward", "NAME", "name"),
    )

    template = """
    {% macro script(this, kwargs) %}
    (function() {
        const map = {{ this._parent.get_name() }};
        const south = __SOUTH__;
        const west = __WEST__;
        const north = __NORTH__;
        const east = __EAST__;
        const imageUrl = __IMAGE_URL__;
        const countyData = __COUNTY_DATA__;
        const constituencyData = __CONSTITUENCY_DATA__;
        const wardData = __WARD_DATA__;
        const classes = __CLASS_DEFINITIONS__;
        const statusLabel = __STATUS_LABEL__;

        const image = new Image();
        const canvas = document.createElement("canvas");
        const ctx = canvas.getContext("2d", {willReadFrequently: true});
        let imageReady = false;

        image.onload = function() {
            canvas.width = image.naturalWidth;
            canvas.height = image.naturalHeight;
            ctx.drawImage(image, 0, 0);
            imageReady = true;
        };
        image.src = imageUrl;

        function pointInRing(lng, lat, ring) {
            let inside = false;
            for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
                const xi = ring[i][0], yi = ring[i][1];
                const xj = ring[j][0], yj = ring[j][1];
                const intersects =
                    ((yi > lat) !== (yj > lat)) &&
                    (lng < ((xj - xi) * (lat - yi)) / ((yj - yi) || 1e-12) + xi);
                if (intersects) inside = !inside;
            }
            return inside;
        }

        function pointInPolygon(lng, lat, rings) {
            if (!rings || !rings.length || !pointInRing(lng, lat, rings[0])) {
                return false;
            }
            for (let i = 1; i < rings.length; i++) {
                if (pointInRing(lng, lat, rings[i])) return false;
            }
            return true;
        }

        function geometryContains(geometry, lng, lat) {
            if (!geometry) return false;
            if (geometry.type === "Polygon") {
                return pointInPolygon(lng, lat, geometry.coordinates);
            }
            if (geometry.type === "MultiPolygon") {
                return geometry.coordinates.some(
                    polygon => pointInPolygon(lng, lat, polygon)
                );
            }
            return false;
        }

        function findAdminName(collection, lng, lat) {
            if (!collection || !collection.features) return null;
            for (const feature of collection.features) {
                if (geometryContains(feature.geometry, lng, lat)) {
                    return feature.properties && feature.properties.lookup_name
                        ? String(feature.properties.lookup_name)
                        : null;
                }
            }
            return null;
        }

        function classifyPixel(r, g, b, a) {
            if (a === 0) return null;

            let best = null;
            let bestDistance = Infinity;
            for (const item of classes) {
                const dr = r - item.rgb[0];
                const dg = g - item.rgb[1];
                const db = b - item.rgb[2];
                const distance = dr * dr + dg * dg + db * db;
                if (distance < bestDistance) {
                    bestDistance = distance;
                    best = item;
                }
            }
            return best;
        }

        map.on("click", function(e) {
            if (!imageReady) return;

            const lat = e.latlng.lat;
            const lng = e.latlng.lng;

            if (lat < south || lat > north || lng < west || lng > east) {
                return;
            }

            const xRatio = (lng - west) / (east - west);
            const yRatio = (north - lat) / (north - south);
            const x = Math.max(
                0,
                Math.min(canvas.width - 1, Math.floor(xRatio * canvas.width))
            );
            const y = Math.max(
                0,
                Math.min(canvas.height - 1, Math.floor(yRatio * canvas.height))
            );

            const pixel = ctx.getImageData(x, y, 1, 1).data;
            const risk = classifyPixel(pixel[0], pixel[1], pixel[2], pixel[3]);
            if (!risk) return;

            const county = findAdminName(countyData, lng, lat) || "Unknown";
            const constituency =
                findAdminName(constituencyData, lng, lat) || "Unknown";
            const ward = findAdminName(wardData, lng, lat) || "Unknown";

            const popupHtml = `
                <div style="color: black; padding: 5px; margin: 0; font-size: 12px;">
                    <strong style="font-size: 12px; color: black;">${statusLabel}: ${risk.label}</strong><br>
                    <div style="font-size: 12px;"><strong>County:</strong> ${county}</div>
                    <div style="font-size: 12px;"><strong>Constituency:</strong> ${constituency}</div>
                    <div style="font-size: 12px;"><strong>Ward:</strong> ${ward}</div>
                </div>
            `;

            L.popup({maxWidth: 300, closeButton: true})
                .setLatLng(e.latlng)
                .setContent(popupHtml)
                .openOn(map);
        });
    })();
    {% endmacro %}
    """

    replacements = {
        "__SOUTH__": repr(float(south)),
        "__WEST__": repr(float(west)),
        "__NORTH__": repr(float(north)),
        "__EAST__": repr(float(east)),
        "__IMAGE_URL__": json.dumps(image_url),
        "__COUNTY_DATA__": json.dumps(county_data, separators=(",", ":")),
        "__CONSTITUENCY_DATA__": json.dumps(constituency_data, separators=(",", ":")),
        "__WARD_DATA__": json.dumps(ward_data, separators=(",", ":")),
        "__INITIAL_MEDIUM__": json.dumps(initial_medium),
        "__STATUS_LABEL__": json.dumps("Water safety" if medium == "Water" else "Contamination"),
        "__CLASS_DEFINITIONS__": json.dumps(
            [
                {"rgb": [33, 150, 243], "label": "Safe"},
                {"rgb": [255, 235, 59], "label": "Unsafe"},
            ]
            if medium == "Water"
            else [
                {"rgb": [76, 175, 80], "label": "Clean"},
                {"rgb": [255, 235, 59], "label": "Slightly contaminated"},
                {"rgb": [255, 152, 0], "label": "Moderate"},
                {"rgb": [244, 67, 54], "label": "Heavy contamination"},
            ],
            separators=(",", ":"),
        ),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)

    click_handler = MacroElement()
    click_handler._name = "InstantRasterClick"
    click_handler._template = Template(template)
    m.add_child(click_handler)


def persist_upload(uploaded_file, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(uploaded_file.getbuffer())
    get_raster_src.clear()
    prepare_raster_overlay.clear()
    prepare_water_overlay.clear()
    return str(dest)


def resolve_raster_path(medium: str, uploaded_file) -> str | None:
    if medium == "Soil":
        if uploaded_file is not None:
            dest = UPLOAD_DIR / f"soil_{uploaded_file.name}"
            return persist_upload(uploaded_file, dest)
        return str(SOIL_RASTER) if SOIL_RASTER.exists() else None

    if uploaded_file is not None:
        dest = UPLOAD_DIR / f"water_{uploaded_file.name}"
        return persist_upload(uploaded_file, dest)

    return str(WATER_RASTER) if WATER_RASTER.exists() else None


def add_vector_layers(m: folium.Map) -> None:
    """Add vector layers (wards, constituencies, county) to the map with layer control."""
    # Add Wards layer with thin grey line
    if WARDS_GEOJSON.exists():
        try:
            wards_layer = folium.FeatureGroup(name="Wards")
            folium.GeoJson(
                str(WARDS_GEOJSON),
                style_function=lambda x: {
                    'fillColor': 'transparent',
                    'color': '#111111',
                    'weight': 0.25,
                    'fillOpacity': 0.0,
                },
            ).add_to(wards_layer)
            wards_layer.add_to(m)
        except Exception as e:
            pass

    # Add Constituencies layer
    if CONSTITUENCIES_GEOJSON.exists():
        try:
            constituencies_layer = folium.FeatureGroup(name="Sub-counties")
            folium.GeoJson(
                str(CONSTITUENCIES_GEOJSON),
                style_function=lambda x: {
                    'fillColor': 'transparent',
                    'color': '#bfc3c9',
                    'weight': 0.7,
                    'fillOpacity': 0.0,
                },
            ).add_to(constituencies_layer)
            constituencies_layer.add_to(m)
        except Exception as e:
            pass

    # Add County boundary layer
    if COUNTY_GEOJSON.exists():
        try:
            county_layer = folium.FeatureGroup(name="Kakamega County Boundary")
            folium.GeoJson(
                str(COUNTY_GEOJSON),
                style_function=lambda x: {
                    'fillColor': '#e31a1c',
                    'color': '#e31a1c',
                    'weight': 3,
                    'fillOpacity': 0.0,
                },
            ).add_to(county_layer)
            county_layer.add_to(m)
        except Exception as e:
            pass


@st.cache_data(show_spinner=False)
def load_sample_points(path_string: str) -> gpd.GeoDataFrame:
    """Load sample points in WGS84, falling back to DBF coordinates if SHX is missing."""
    path = Path(path_string)
    if not path.exists():
        return gpd.GeoDataFrame()

    try:
        gdf = gpd.read_file(path)
        if gdf.crs is not None and str(gdf.crs) != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        return gdf
    except Exception:
        # Some uploaded shapefile sets are missing the .shx index.
        # Both sample DBFs contain latitude/longitude fields, so rebuild
        # point geometry directly from those attributes instead.
        dbf_path = path.with_suffix(".dbf")
        if not dbf_path.exists():
            return gpd.GeoDataFrame()

        records = _read_dbf_records(dbf_path)
        if not records:
            return gpd.GeoDataFrame()

        import pandas as pd

        df = pd.DataFrame(records)

        lat_field = next(
            (name for name in ("LATITUDE", "Latitude", "latitude", "LAT", "Lat") if name in df.columns),
            None,
        )
        lon_field = next(
            (name for name in ("Longitude", "LONGITUDE", "longitude", "LON", "Lon") if name in df.columns),
            None,
        )

        if lat_field is None or lon_field is None:
            return gpd.GeoDataFrame(df)

        df[lat_field] = pd.to_numeric(df[lat_field], errors="coerce")
        df[lon_field] = pd.to_numeric(df[lon_field], errors="coerce")
        df = df.dropna(subset=[lat_field, lon_field]).copy()

        return gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df[lon_field], df[lat_field]),
            crs="EPSG:4326",
        )


def _read_dbf_records(dbf_path: Path) -> list[dict]:
    """Minimal DBF reader for the sample tables using only the Python standard library."""
    with dbf_path.open("rb") as fh:
        header = fh.read(32)
        if len(header) < 32:
            return []

        num_records = struct.unpack("<I", header[4:8])[0]
        header_len = struct.unpack("<H", header[8:10])[0]
        record_len = struct.unpack("<H", header[10:12])[0]

        fields = []
        while True:
            first = fh.read(1)
            if not first or first == b"\r":
                break

            descriptor = first + fh.read(31)
            raw_name = descriptor[:11].split(b"\x00", 1)[0]
            name = raw_name.decode("latin1", errors="ignore").strip()
            field_type = chr(descriptor[11])
            length = descriptor[16]
            decimals = descriptor[17]
            fields.append((name, field_type, length, decimals))

        fh.seek(header_len)
        records = []

        for _ in range(num_records):
            row = fh.read(record_len)
            if len(row) < record_len:
                break
            if row[:1] == b"*":
                continue

            pos = 1
            record = {}
            for name, field_type, length, decimals in fields:
                raw = row[pos:pos + length]
                pos += length
                text = raw.decode("latin1", errors="ignore").strip()

                if not text:
                    record[name] = None
                elif field_type in ("N", "F"):
                    try:
                        record[name] = float(text)
                    except ValueError:
                        record[name] = text
                elif field_type == "L":
                    record[name] = text.upper() in ("Y", "T")
                else:
                    record[name] = text

            records.append(record)

        return records


def _soil_sample_color(value) -> str:
    text = str(value or "").strip().lower()
    if "heavy" in text:
        return "#F44336"
    if "moderate" in text:
        return "#FF9800"
    if "slight" in text:
        return "#FFEB3B"
    if "clean" in text:
        return "#4CAF50"
    return "#9E9E9E"


def _water_sample_color(value) -> str:
    text = str(value or "").strip().lower()
    if text == "safe":
        return "#4CAF50"
    if text == "unsafe":
        return "#F44336"
    return "#9E9E9E"


def class_advice(medium: str, class_label: str) -> str:
    label = str(class_label or "").strip().lower()
    if medium == "Water":
        if "unsafe" in label:
            return "At least one tested metal is predicted to exceed WHO drinking-water guidelines. Do not drink untreated; have the water tested."
        return "No tested metal is predicted to exceed WHO guidelines."

    if "heavy" in label:
        return "High contamination is likely. Avoid growing food crops here and have the soil tested before use."
    if "moderate" in label:
        return "Some contamination is likely. Test the soil before growing food crops."
    if "slight" in label:
        return "Slight contamination is possible. Wash produce well and test the soil before farming."
    return "No contamination is predicted, the soil is safe to grow food crops."


def _metal_table_for_medium(medium: str) -> pd.DataFrame:
    path = SOIL_METALS_TABLE if medium == "Soil" else WATER_METALS_TABLE
    table = load_compressed_csv(str(path))
    if table.empty or "ID" not in table.columns:
        return table
    valid = table["ID"].astype(str).str.fullmatch(r"kak\d+", na=False)
    return table.loc[valid].copy()


def sample_metal_summary_html(sample_id: str, medium: str) -> str:
    table = _metal_table_for_medium(medium)
    if table.empty or "ID" not in table.columns:
        return "Not available"

    rows = table[table["ID"].astype(str) == str(sample_id)]
    if rows.empty:
        return "Not available"

    row = rows.iloc[0]
    suffix = "mg_kg" if medium == "Soil" else "mg_L"
    unit = "mg/kg" if medium == "Soil" else "mg/L"
    parts = []
    for metal in ["Hg", "As", "Pb", "Cd", "Cr", "Cu", "Zn", "Ni"]:
        col = f"{metal}_{suffix}"
        if col not in row.index or pd.isna(row[col]):
            continue
        try:
            value = float(row[col])
            parts.append(f"{metal}: {value:.5g} {unit}")
        except Exception:
            parts.append(f"{metal}: {row[col]} {unit}")
    return "<br>".join(parts) if parts else "Not available"


def sample_dominant_metals(sample_id: str, medium: str) -> str:
    table = _metal_table_for_medium(medium)
    if table.empty or "ID" not in table.columns or "Dominant_Metal" not in table.columns:
        return "Not available"
    rows = table[table["ID"].astype(str) == str(sample_id)]
    metals = [m for m in rows["Dominant_Metal"].dropna().astype(str).unique() if m.strip()]
    return ", ".join(metals[:3]) if metals else "Not available"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_sample_context(lat: float, lon: float, medium: str) -> dict:
    path = SOIL_SAMPLE_POINTS if medium == "Soil" else WATER_SAMPLE_POINTS
    gdf = load_sample_points(str(path))
    if gdf.empty:
        return {"distance_km": None, "sample_id": None, "dominant_metals": "Not available"}

    best = None
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        d = _haversine_km(lat, lon, float(geom.y), float(geom.x))
        if best is None or d < best["distance_km"]:
            sid = str(row.get("ID", ""))
            best = {
                "distance_km": d,
                "sample_id": sid,
                "dominant_metals": sample_dominant_metals(sid, medium),
            }
    return best or {"distance_km": None, "sample_id": None, "dominant_metals": "Not available"}


def add_sample_point_layers(m: folium.Map):
    """Add hidden soil and water sample layers with guide-compliant popups."""
    soil_layer = folium.FeatureGroup(name="Soil sample points", show=False, control=False)
    water_layer = folium.FeatureGroup(name="Water sample points", show=False, control=False)

    soil_gdf = load_sample_points(str(SOIL_SAMPLE_POINTS))
    if not soil_gdf.empty:
        for _, row in soil_gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            sample_id = str(row.get("ID", ""))
            category = str(row.get("Overall_cl", ""))
            metals = sample_dominant_metals(sample_id, "Soil")
            concentrations = sample_metal_summary_html(sample_id, "Soil")
            advice = class_advice("Soil", category)
            popup = f"""
            <div style="font-size:12px;color:#111;min-width:230px;">
                <strong>Soil sample: {sample_id}</strong><br>
                <strong>Coordinates:</strong> {float(geom.y):.6f}, {float(geom.x):.6f}<br>
                <strong>Class:</strong> {category}<br>
                <strong>Dominant metal(s):</strong> {metals}<br>
                <strong>Metal concentrations:</strong><br>{concentrations}<br>
                <strong>Advice:</strong> {advice}
            </div>
            """
            folium.CircleMarker(
                location=[float(geom.y), float(geom.x)],
                radius=5,
                color="#FFFFFF",
                weight=1.2,
                fill=True,
                fill_color=_soil_sample_color(category),
                fill_opacity=0.95,
                popup=folium.Popup(popup, max_width=320),
            ).add_to(soil_layer)

    water_gdf = load_sample_points(str(WATER_SAMPLE_POINTS))
    if not water_gdf.empty:
        for _, row in water_gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            sample_id = str(row.get("ID", ""))
            category = str(row.get("Safety_cla", ""))
            metals = sample_dominant_metals(sample_id, "Water")
            concentrations = sample_metal_summary_html(sample_id, "Water")
            advice = class_advice("Water", category)
            popup = f"""
            <div style="font-size:12px;color:#111;min-width:230px;">
                <strong>Water sample: {sample_id}</strong><br>
                <strong>Coordinates:</strong> {float(geom.y):.6f}, {float(geom.x):.6f}<br>
                <strong>Class:</strong> {category}<br>
                <strong>Dominant metal(s):</strong> {metals}<br>
                <strong>Metal concentrations:</strong><br>{concentrations}<br>
                <strong>Advice:</strong> {advice}
            </div>
            """
            folium.CircleMarker(
                location=[float(geom.y), float(geom.x)],
                radius=5,
                color="#FFFFFF",
                weight=1.2,
                fill=True,
                fill_color=_water_sample_color(category),
                fill_opacity=0.95,
                popup=folium.Popup(popup, max_width=320),
            ).add_to(water_layer)

    soil_layer.add_to(m)
    water_layer.add_to(m)
    return soil_layer, water_layer


def add_leaflet_internal_css(m: folium.Map) -> None:
    """Style Leaflet controls inside the Folium iframe."""
    css = """
    <style>
    .leaflet-top.leaflet-right .leaflet-control-layers {
        margin-top: 48px !important;
        margin-right: 10px !important;
        min-width: 112px !important;
        max-width: 145px !important;
        max-height: 175px !important;
        overflow-y: auto !important;
        padding: 3px 5px !important;
        background: rgba(58, 58, 58, 0.50) !important;
        border: 1px solid rgba(255,255,255,0.18) !important;
        border-radius: 4px !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.28) !important;
        color: #ffffff !important;
    }

    .leaflet-control-layers-expanded {
        padding: 3px 5px !important;
        color: #ffffff !important;
    }

    .leaflet-control-layers-base,
    .leaflet-control-layers-overlays {
        margin: 0 !important;
    }

    .leaflet-control-layers label {
        display: block !important;
        margin: 0 !important;
        padding: 0 !important;
        line-height: 1.02 !important;
        font-size: 10px !important;
        font-weight: 700 !important;
        color: #ffffff !important;
        white-space: nowrap !important;
    }

    .leaflet-control-layers-selector {
        width: 9px !important;
        height: 9px !important;
        margin: 0 3px 0 0 !important;
        vertical-align: middle !important;
    }

    .leaflet-control-layers-separator {
        height: 0 !important;
        margin: 2px 0 !important;
        border-top: 1px solid rgba(255,255,255,0.22) !important;
    }

    .leaflet-control-layers-list {
        margin: 0 !important;
        color: #ffffff !important;
    }

    .leaflet-control-layers-scrollbar {
        overflow-y: auto !important;
    }

    .leaflet-control-layers::-webkit-scrollbar {
        width: 4px;
    }

    .leaflet-control-layers::-webkit-scrollbar-thumb {
        background: rgba(255,255,255,0.35);
        border-radius: 4px;
    }
    </style>
    """
    m.get_root().header.add_child(folium.Element(css))


def create_base_map(center_lat: float, center_lon: float, zoom: int = 10) -> folium.Map:
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        control_scale=True,
        tiles=None,
        attr="Map",
    )

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        name="Satellite",
        overlay=False,
        control=True,
        show=True,
    ).add_to(m)

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Esri, HERE, Garmin, USGS, Intermap, INCREMENT P, NRCan, METI, and the GIS User Community",
        name="Roads and places",
        overlay=False,
        control=True,
        show=False,
    ).add_to(m)

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        overlay=False,
        control=True,
        show=False,
    ).add_to(m)

    Fullscreen(position="topleft").add_to(m)
    LocateControl(position="topleft", flyTo=True).add_to(m)
    MousePosition(
        position="bottomleft",
        separator=" , ",
        prefix="WGS84",
        lat_formatter="function(num) {return L.Util.formatNum(num, 5);}",
        lng_formatter="function(num) {return L.Util.formatNum(num, 5);}",
    ).add_to(m)

    # Add vector layers
    add_vector_layers(m)

    return m


def add_raster_overlay(
    m: folium.Map,
    raster_path: str,
    opacity: float,
    layer_name: str,
    medium: str = "Soil",
):
    rgba_image, bounds, metadata = prepare_raster_overlay(raster_path)
    if rgba_image is None or bounds is None:
        return None, metadata, None

    overlay = ImageOverlay(
        image=_encode_png(rgba_image),
        bounds=bounds,
        opacity=opacity,
        name=layer_name,
        interactive=False,
        cross_origin=False,
        zindex=1,
    )
    overlay.add_to(m)
    return overlay, metadata, bounds


def add_interactive_medium_controls(
    m: folium.Map,
    soil_overlay: ImageOverlay,
    soil_rgba,
    soil_bounds,
    water_overlay: ImageOverlay,
    water_rgba,
    water_bounds,
    county_bounds,
    soil_sample_layer,
    water_sample_layer,
    initial_medium: str = "Soil",
) -> None:
    """Switch Soil/Water, identify pixels, center, and change opacity fully in Leaflet."""
    county_data = _admin_lookup_geojson(
        str(COUNTY_GEOJSON),
        ("ADM1_EN", "COUNTY", "County", "county", "NAME_1"),
    )
    constituency_data = _admin_lookup_geojson(
        str(CONSTITUENCIES_GEOJSON),
        ("ADM2_EN", "CONSTITUEN", "Constituency", "constituency", "NAME_2"),
    )
    ward_data = _admin_lookup_geojson(
        str(WARDS_GEOJSON),
        ("ward", "WARD", "Ward", "NAME", "name"),
    )

    soil_url = _encode_png(soil_rgba)
    water_url = _encode_png(water_rgba)

    template = """
    {% macro script(this, kwargs) %}
    (function() {
        const map = {{ this._parent.get_name() }};
        const soilOverlay = __SOIL_OVERLAY__;
        const waterOverlay = __WATER_OVERLAY__;
        const soilSamples = __SOIL_SAMPLE_LAYER__;
        const waterSamples = __WATER_SAMPLE_LAYER__;

        const soilBounds = L.latLngBounds(
            [__SOIL_SOUTH__, __SOIL_WEST__],
            [__SOIL_NORTH__, __SOIL_EAST__]
        );
        const waterBounds = L.latLngBounds(
            [__WATER_SOUTH__, __WATER_WEST__],
            [__WATER_NORTH__, __WATER_EAST__]
        );
        const countyBounds = L.latLngBounds(
            [__COUNTY_SOUTH__, __COUNTY_WEST__],
            [__COUNTY_NORTH__, __COUNTY_EAST__]
        );

        const countyData = __COUNTY_DATA__;
        const constituencyData = __CONSTITUENCY_DATA__;
        const wardData = __WARD_DATA__;

        const soilClasses = [
            {rgb: [76, 175, 80], label: "Clean"},
            {rgb: [255, 235, 59], label: "Slightly contaminated"},
            {rgb: [255, 152, 0], label: "Moderate"},
            {rgb: [244, 67, 54], label: "Heavy contamination"}
        ];
        const waterClasses = [
            {rgb: [76, 175, 80], label: "Safe"},
            {rgb: [244, 67, 54], label: "Unsafe"}
        ];

        let activeMedium = "Soil";
        let currentOpacity = 0.7;
        let samplePointsVisible = false;

        function makeCanvas(url) {
            const image = new Image();
            const canvas = document.createElement("canvas");
            const ctx = canvas.getContext("2d", {willReadFrequently: true});
            const state = {image, canvas, ctx, ready: false};
            image.onload = function() {
                canvas.width = image.naturalWidth;
                canvas.height = image.naturalHeight;
                ctx.drawImage(image, 0, 0);
                state.ready = true;
            };
            image.src = url;
            return state;
        }

        const soilRaster = makeCanvas(__SOIL_URL__);
        const waterRaster = makeCanvas(__WATER_URL__);

        function pointInRing(lng, lat, ring) {
            let inside = false;
            for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
                const xi = ring[i][0], yi = ring[i][1];
                const xj = ring[j][0], yj = ring[j][1];
                const intersects =
                    ((yi > lat) !== (yj > lat)) &&
                    (lng < ((xj - xi) * (lat - yi)) / ((yj - yi) || 1e-12) + xi);
                if (intersects) inside = !inside;
            }
            return inside;
        }

        function pointInPolygon(lng, lat, rings) {
            if (!rings || !rings.length || !pointInRing(lng, lat, rings[0])) return false;
            for (let i = 1; i < rings.length; i++) {
                if (pointInRing(lng, lat, rings[i])) return false;
            }
            return true;
        }

        function geometryContains(geometry, lng, lat) {
            if (!geometry) return false;
            if (geometry.type === "Polygon") return pointInPolygon(lng, lat, geometry.coordinates);
            if (geometry.type === "MultiPolygon") {
                return geometry.coordinates.some(p => pointInPolygon(lng, lat, p));
            }
            return false;
        }

        function findAdminName(collection, lng, lat) {
            if (!collection || !collection.features) return null;
            for (const feature of collection.features) {
                if (geometryContains(feature.geometry, lng, lat)) {
                    return feature.properties && feature.properties.lookup_name
                        ? String(feature.properties.lookup_name)
                        : null;
                }
            }
            return null;
        }

        function classifyPixel(r, g, b, a, classes) {
            if (a === 0) return null;
            let best = null;
            let bestDistance = Infinity;
            for (const item of classes) {
                const dr = r - item.rgb[0];
                const dg = g - item.rgb[1];
                const db = b - item.rgb[2];
                const distance = dr * dr + dg * dg + db * db;
                if (distance < bestDistance) {
                    bestDistance = distance;
                    best = item;
                }
            }
            return best;
        }

        const legend = L.control({position: "bottomright"});
        legend.onAdd = function() {
            const div = L.DomUtil.create("div", "kakamega-dynamic-legend");
            div.style.background = "rgba(255,255,255,0.94)";
            div.style.padding = "9px 11px";
            div.style.border = "1px solid #c4a35a";
            div.style.fontFamily = "Georgia,serif";
            div.style.fontSize = "12px";
            div.style.color = "#152238";
            div.style.minWidth = "155px";
            div.style.marginBottom = "38px";
            div.style.boxShadow = "0 2px 8px rgba(21,34,56,0.18)";
            L.DomEvent.disableClickPropagation(div);
            return div;
        };
        legend.addTo(map);

        function updateLegend() {
            const div = document.querySelector(".kakamega-dynamic-legend");
            if (!div) return;
            if (activeMedium === "Water") {
                div.innerHTML =
                    '<div style="font-weight:700;margin-bottom:6px;border-bottom:1px solid #c4a35a;padding-bottom:4px;">Water safety</div>' +
                    '<div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#4CAF50;border:1px solid #333;margin-right:6px;"></span>Safe</div>' +
                    '<div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#F44336;border:1px solid #333;margin-right:6px;"></span>Unsafe</div>';
            } else {
                div.innerHTML =
                    '<div style="font-weight:700;margin-bottom:6px;border-bottom:1px solid #c4a35a;padding-bottom:4px;">Contamination risk</div>' +
                    '<div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#4CAF50;border:1px solid #333;margin-right:6px;"></span>Clean</div>' +
                    '<div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FFEB3B;border:1px solid #333;margin-right:6px;"></span>Slightly contaminated</div>' +
                    '<div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FF9800;border:1px solid #333;margin-right:6px;"></span>Moderate</div>' +
                    '<div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#F44336;border:1px solid #333;margin-right:6px;"></span>Heavy contamination</div>';
            }
        }

        function sampleLayerForActiveMedium() {
            return activeMedium === "Water" ? waterSamples : soilSamples;
        }

        function removeBothSampleLayers() {
            if (map.hasLayer(soilSamples)) map.removeLayer(soilSamples);
            if (map.hasLayer(waterSamples)) map.removeLayer(waterSamples);
        }

        function updateSampleToggle() {
            const btn = document.querySelector(".kakamega-sample-toggle");
            if (!btn) return;

            const mediumName = activeMedium.toLowerCase();
            const eye = btn.querySelector(".sample-eye-svg");
            const slash = btn.querySelector(".sample-eye-slash");
            const label = btn.querySelector(".sample-toggle-label");

            if (samplePointsVisible) {
                btn.style.opacity = "1";
                if (slash) slash.style.display = "none";
                if (label) label.textContent = "Hide " + mediumName + " sample points";
            } else {
                btn.style.opacity = "0.68";
                if (slash) slash.style.display = "block";
                if (label) label.textContent = "View " + mediumName + " sample points";
            }
        }

        function setMedium(medium) {
            activeMedium = medium;
            samplePointsVisible = false;
            removeBothSampleLayers();
            if (medium === "Water") {
                if (map.hasLayer(soilOverlay)) map.removeLayer(soilOverlay);
                if (!map.hasLayer(waterOverlay)) waterOverlay.addTo(map);
                waterOverlay.setOpacity(currentOpacity);
            } else {
                if (map.hasLayer(waterOverlay)) map.removeLayer(waterOverlay);
                if (!map.hasLayer(soilOverlay)) soilOverlay.addTo(map);
                soilOverlay.setOpacity(currentOpacity);
            }
            updateLegend();
            document.querySelectorAll(".kakamega-medium-btn").forEach(btn => {
                const active = btn.dataset.medium === activeMedium;
                btn.style.background = active ? "#ff4b4b" : "rgba(255,255,255,0.92)";
                btn.style.color = active ? "#fff" : "#222";
            });
            updateSampleToggle();
            map.closePopup();
        }

        const SampleToggleControl = L.Control.extend({
            options: {position: "topleft"},
            onAdd: function() {
                const container = L.DomUtil.create(
                    "div",
                    "kakamega-sample-toggle"
                );
                container.title = "Show or hide sample points";
                container.style.display = "flex";
                container.style.alignItems = "center";
                container.style.gap = "7px";
                container.style.background = "rgba(255,255,255,0.92)";
                container.style.color = "#222";
                container.style.padding = "5px 9px";
                container.style.borderRadius = "4px";
                container.style.boxShadow = "0 1px 5px rgba(0,0,0,0.35)";
                container.style.cursor = "pointer";
                container.style.fontSize = "12px";
                container.style.fontWeight = "600";
                container.style.whiteSpace = "nowrap";
                container.style.opacity = "0.68";

                const iconWrap = L.DomUtil.create("span", "", container);
                iconWrap.style.width = "19px";
                iconWrap.style.height = "14px";
                iconWrap.style.position = "relative";
                iconWrap.innerHTML =
                    '<svg class="sample-eye-svg" width="19" height="14" viewBox="0 0 24 18" aria-hidden="true">' +
                    '<path d="M1 9C4.2 3.8 7.8 1.5 12 1.5S19.8 3.8 23 9c-3.2 5.2-6.8 7.5-11 7.5S4.2 14.2 1 9Z" fill="none" stroke="currentColor" stroke-width="1.8"/>' +
                    '<circle cx="12" cy="9" r="3.2" fill="currentColor"/>' +
                    '</svg>' +
                    '<span class="sample-eye-slash" style="position:absolute;left:8px;top:-3px;width:2px;height:20px;background:currentColor;transform:rotate(-45deg);transform-origin:center;"></span>';

                const label = L.DomUtil.create("span", "sample-toggle-label", container);
                label.textContent = "View soil sample points";

                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.on(container, "click", function(e) {
                    L.DomEvent.preventDefault(e);
                    samplePointsVisible = !samplePointsVisible;
                    removeBothSampleLayers();
                    if (samplePointsVisible) {
                        sampleLayerForActiveMedium().addTo(map);
                    }
                    updateSampleToggle();
                });

                return container;
            }
        });
        map.addControl(new SampleToggleControl());

        const CenterControl = L.Control.extend({
            options: {position: "topleft"},
            onAdd: function() {
                const container = L.DomUtil.create("div", "leaflet-bar");
                const btn = L.DomUtil.create("a", "", container);
                btn.href = "#";
                btn.title = "Fit Kakamega County";
                btn.innerHTML = "⌖";
                btn.style.fontSize = "22px";
                btn.style.width = "30px";
                btn.style.height = "30px";
                btn.style.lineHeight = "30px";
                btn.style.textAlign = "center";
                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.on(btn, "click", function(e) {
                    L.DomEvent.preventDefault(e);
                    map.fitBounds(countyBounds, {
                        animate: true,
                        duration: 0.2,
                        padding: [8, 8]
                    });
                });
                return container;
            }
        });
        map.addControl(new CenterControl());

        const OpacityControl = L.Control.extend({
            options: {position: "topright"},
            onAdd: function() {
                const container = L.DomUtil.create("div", "");
                container.style.background = "transparent";
                container.style.display = "flex";
                container.style.alignItems = "center";
                container.style.gap = "6px";

                const icon = L.DomUtil.create("span", "", container);
                icon.innerHTML = "◐";
                icon.style.color = "#fff";
                icon.style.fontSize = "17px";
                icon.style.textShadow = "0 1px 2px rgba(0,0,0,0.65)";

                const slider = L.DomUtil.create("input", "", container);
                slider.type = "range";
                slider.min = "0.10";
                slider.max = "1.00";
                slider.step = "0.05";
                slider.value = "0.70";
                slider.style.width = "105px";
                slider.style.cursor = "pointer";
                slider.style.accentColor = "#fff";
                slider.addEventListener("input", function() {
                    currentOpacity = parseFloat(slider.value);
                    if (activeMedium === "Water") waterOverlay.setOpacity(currentOpacity);
                    else soilOverlay.setOpacity(currentOpacity);
                });

                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.disableScrollPropagation(container);
                return container;
            }
        });
        map.addControl(new OpacityControl());

        map.on("click", function(e) {
            const raster = activeMedium === "Water" ? waterRaster : soilRaster;
            const bounds = activeMedium === "Water" ? waterBounds : soilBounds;
            const classes = activeMedium === "Water" ? waterClasses : soilClasses;
            if (!raster.ready || !bounds.contains(e.latlng)) return;

            const sw = bounds.getSouthWest();
            const ne = bounds.getNorthEast();
            const xRatio = (e.latlng.lng - sw.lng) / (ne.lng - sw.lng);
            const yRatio = (ne.lat - e.latlng.lat) / (ne.lat - sw.lat);
            const x = Math.max(0, Math.min(raster.canvas.width - 1, Math.floor(xRatio * raster.canvas.width)));
            const y = Math.max(0, Math.min(raster.canvas.height - 1, Math.floor(yRatio * raster.canvas.height)));

            const pixel = raster.ctx.getImageData(x, y, 1, 1).data;
            const status = classifyPixel(pixel[0], pixel[1], pixel[2], pixel[3], classes);
            if (!status) return;

            const county = findAdminName(countyData, e.latlng.lng, e.latlng.lat) || "Unknown";
            const constituency = findAdminName(constituencyData, e.latlng.lng, e.latlng.lat) || "Unknown";
            const ward = findAdminName(wardData, e.latlng.lng, e.latlng.lat) || "Unknown";
            const label = activeMedium === "Water" ? "Water safety" : "Contamination";

            const popupHtml =
                '<div style="color:black;padding:5px;margin:0;font-size:12px;">' +
                '<strong style="font-size:12px;color:black;">' + label + ': ' + status.label + '</strong><br>' +
                '<div style="font-size:12px;"><strong>County:</strong> ' + county + '</div>' +
                '<div style="font-size:12px;"><strong>Constituency:</strong> ' + constituency + '</div>' +
                '<div style="font-size:12px;"><strong>Ward:</strong> ' + ward + '</div>' +
                '</div>';

            L.popup({maxWidth: 300, closeButton: true})
                .setLatLng(e.latlng)
                .setContent(popupHtml)
                .openOn(map);
        });

        setMedium(__INITIAL_MEDIUM__);
    })();
    {% endmacro %}
    """

    replacements = {
        "__SOIL_OVERLAY__": soil_overlay.get_name(),
        "__WATER_OVERLAY__": water_overlay.get_name(),
        "__SOIL_SAMPLE_LAYER__": soil_sample_layer.get_name(),
        "__WATER_SAMPLE_LAYER__": water_sample_layer.get_name(),
        "__SOIL_SOUTH__": repr(float(soil_bounds[0][0])),
        "__SOIL_WEST__": repr(float(soil_bounds[0][1])),
        "__SOIL_NORTH__": repr(float(soil_bounds[1][0])),
        "__SOIL_EAST__": repr(float(soil_bounds[1][1])),
        "__WATER_SOUTH__": repr(float(water_bounds[0][0])),
        "__WATER_WEST__": repr(float(water_bounds[0][1])),
        "__WATER_NORTH__": repr(float(water_bounds[1][0])),
        "__WATER_EAST__": repr(float(water_bounds[1][1])),
        "__COUNTY_SOUTH__": repr(float(county_bounds[0][0])),
        "__COUNTY_WEST__": repr(float(county_bounds[0][1])),
        "__COUNTY_NORTH__": repr(float(county_bounds[1][0])),
        "__COUNTY_EAST__": repr(float(county_bounds[1][1])),
        "__SOIL_URL__": json.dumps(soil_url),
        "__WATER_URL__": json.dumps(water_url),
        "__COUNTY_DATA__": json.dumps(county_data, separators=(",", ":")),
        "__CONSTITUENCY_DATA__": json.dumps(constituency_data, separators=(",", ":")),
        "__WARD_DATA__": json.dumps(ward_data, separators=(",", ":")),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)

    controls = MacroElement()
    controls._name = "InteractiveMediumControls"
    controls._template = Template(template)
    m.add_child(controls)


def add_map_legend(m: folium.Map, medium: str = "Soil") -> None:
    if medium == "Water":
        legend_items = """
          <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#4CAF50;border:1px solid #333;margin-right:6px;"></span>Safe</div>
          <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#F44336;border:1px solid #333;margin-right:6px;"></span>Unsafe</div>
        """
        legend_title = "Water safety"
    else:
        legend_items = """
          <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#4CAF50;border:1px solid #333;margin-right:6px;"></span>Clean</div>
          <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FFEB3B;border:1px solid #333;margin-right:6px;"></span>Slightly contaminated</div>
          <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FF9800;border:1px solid #333;margin-right:6px;"></span>Moderate</div>
          <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#F44336;border:1px solid #333;margin-right:6px;"></span>Heavy contamination</div>
        """
        legend_title = "Contamination risk"

    legend = f"""
    <div style="position:fixed;bottom:58px;right:12px;z-index:999;
                background:rgba(255,255,255,0.94);padding:10px 12px;
                border:1px solid #c4a35a;font-family:Georgia,serif;font-size:12px;
                color:#152238;min-width:168px;box-shadow:0 2px 8px rgba(21,34,56,0.18);">
      <div style="font-weight:700;margin-bottom:6px;border-bottom:1px solid #c4a35a;padding-bottom:4px;">{legend_title}</div>
      {legend_items}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))


def get_admin_info(lat: float, lon: float) -> dict:
    """Get administrative information (county, constituency, ward) for a point."""
    admin_info = {
        'county': None,
        'constituency': None,
        'ward': None
    }

    point = Point(lon, lat)

    # Check county
    if COUNTY_GEOJSON.exists():
        try:
            county_gdf = gpd.read_file(COUNTY_GEOJSON)
            if county_gdf.crs != 'EPSG:4326':
                county_gdf = county_gdf.to_crs('EPSG:4326')
            for idx, row in county_gdf.iterrows():
                if row.geometry.contains(point):
                    admin_info['county'] = row.get('ADM1_EN', 'Kakamega')
                    break
        except Exception:
            pass

    # Check constituency
    if CONSTITUENCIES_GEOJSON.exists():
        try:
            const_gdf = gpd.read_file(CONSTITUENCIES_GEOJSON)
            if const_gdf.crs != 'EPSG:4326':
                const_gdf = const_gdf.to_crs('EPSG:4326')
            for idx, row in const_gdf.iterrows():
                if row.geometry.contains(point):
                    admin_info['constituency'] = row.get('ADM2_EN', 'Unknown')
                    break
        except Exception:
            pass

    # Check ward
    if WARDS_GEOJSON.exists():
        try:
            ward_gdf = gpd.read_file(WARDS_GEOJSON)
            if ward_gdf.crs != 'EPSG:4326':
                ward_gdf = ward_gdf.to_crs('EPSG:4326')
            for idx, row in ward_gdf.iterrows():
                if row.geometry.contains(point):
                    admin_info['ward'] = row.get('ward', 'Unknown')
                    break
        except Exception:
            pass

    return admin_info


def render_click_marker(m: folium.Map, click: dict, raster_path: str, medium: str):
    lat, lon = click["lat"], click["lng"]
    result = sample_raster_value(raster_path, lat, lon)

    # Get administrative information
    admin_info = get_admin_info(lat, lon)

    if "error" not in result:
        # Build popup HTML with admin info
        popup_parts = [
            f"<strong style='font-size: 12px; color: black;'>Contamination: {result['risk_label']}</strong>",
        ]

        if admin_info['county']:
            popup_parts.append(f"<div style='font-size: 12px;'><strong>County:</strong> {admin_info['county']}</div>")
        if admin_info['constituency']:
            popup_parts.append(f"<div style='font-size: 12px;'><strong>Constituency:</strong> {admin_info['constituency']}</div>")
        if admin_info['ward']:
            popup_parts.append(f"<div style='font-size: 12px;'><strong>Ward:</strong> {admin_info['ward']}</div>")

        popup_html = f"""
        <div style="color: black; padding: 5px; margin: 0; font-size: 12px;">
            {'<br>'.join(popup_parts)}
        </div>
        """
        # Add Marker with popup - use show=True to auto-open
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=300, show=True),
            icon=folium.Icon(color='blue', icon='info-sign')
        ).add_to(m)
    else:
        # Outside raster area - show near Kakamega County info
        popup_parts = [
            f"<strong style='font-size: 12px; color: black;'>Near Kakamega County</strong>",
            f"<div style='font-size: 12px;'><strong>Contamination:</strong> {result.get('risk_label', 'Unknown')}</div>",
        ]

        if admin_info['county']:
            popup_parts.append(f"<div style='font-size: 12px;'><strong>County:</strong> {admin_info['county']}</div>")
        if admin_info['constituency']:
            popup_parts.append(f"<div style='font-size: 12px;'><strong>Constituency:</strong> {admin_info['constituency']}</div>")
        if admin_info['ward']:
            popup_parts.append(f"<div style='font-size: 12px;'><strong>Ward:</strong> {admin_info['ward']}</div>")

        popup_html = f"""
        <div style="color: black; padding: 5px; margin: 0; font-size: 12px;">
            {'<br>'.join(popup_parts)}
        </div>
        """
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=250, show=True),
            icon=folium.Icon(color='red', icon='exclamation-sign')
        ).add_to(m)
    return result


def page_interactive_map(uploaded_file, medium: str):
    soil_path = str(SOIL_RASTER) if SOIL_RASTER.exists() else None
    water_path = str(WATER_RASTER) if WATER_RASTER.exists() else None

    if soil_path is None or water_path is None:
        st.error("Both soil and water raster files are required in data/Raster.")
        return

    soil_rgba, soil_bounds, soil_meta = prepare_raster_overlay(soil_path)
    water_rgba, water_bounds, water_meta = prepare_water_overlay(water_path)

    if soil_rgba is None or soil_bounds is None:
        st.error(f"Failed to load soil raster: {soil_meta.get('error', 'Unknown error')}")
        return
    if water_rgba is None or water_bounds is None:
        st.error(f"Failed to load water raster: {water_meta.get('error', 'Unknown error')}")
        return

    county_bounds = get_county_wgs84_bounds()
    county_center_lat = (county_bounds[0][0] + county_bounds[1][0]) / 2.0
    county_center_lon = (county_bounds[0][1] + county_bounds[1][1]) / 2.0
    m = create_base_map(county_center_lat, county_center_lon, zoom=10)

    soil_overlay = ImageOverlay(
        image=_encode_png(soil_rgba),
        bounds=soil_bounds,
        opacity=0.7,
        name="Predicted risk",
        interactive=False,
        cross_origin=False,
        zindex=1,
        show=(medium == "Soil"),
        control=(medium == "Soil"),
    )
    soil_overlay.add_to(m)

    water_overlay = ImageOverlay(
        image=_encode_png(water_rgba),
        bounds=water_bounds,
        opacity=0.7,
        name="Predicted risk",
        interactive=False,
        cross_origin=False,
        zindex=1,
        show=(medium == "Water"),
        control=(medium == "Water"),
    )
    water_overlay.add_to(m)

    m.fit_bounds(county_bounds)

    soil_sample_layer, water_sample_layer = add_sample_point_layers(m)

    add_interactive_medium_controls(
        m,
        soil_overlay,
        soil_rgba,
        soil_bounds,
        water_overlay,
        water_rgba,
        water_bounds,
        county_bounds,
        soil_sample_layer,
        water_sample_layer,
        initial_medium=medium,
    )

    folium.LayerControl(collapsed=False, position="topright").add_to(m)
    add_leaflet_internal_css(m)

    st.markdown('<div class="map-shell">', unsafe_allow_html=True)
    st_folium(
        m,
        width="stretch",
        height=600,
        returned_objects=[],
        key=f"kakamega-map-{medium.lower()}",
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption(
        "Choose Soil or Water in the sidebar to change the layer. "
        "Use the sample-points eye control, then click a point to see its metal concentrations, class and advice."
    )


def page_check_location(uploaded_file, medium: str):
    st.header("Check My Location")
    st.write(
        "Click the map or enter latitude and longitude to see the predicted contamination risk at that place "
        "before farming, drawing water or managing mine waste."
    )

    raster_path = resolve_raster_path(
        medium,
        uploaded_file if medium == "Soil" else None,
    )
    if not raster_path or not Path(raster_path).exists():
        st.warning(f"{medium} raster data is not available.")
        return

    county_bounds = get_county_wgs84_bounds()
    default_lat = (county_bounds[0][0] + county_bounds[1][0]) / 2.0
    default_lon = (county_bounds[0][1] + county_bounds[1][1]) / 2.0

    input_col1, input_col2, input_col3 = st.columns([1, 1, 0.7])
    with input_col1:
        lat = st.number_input(
            "Latitude",
            value=float(st.session_state.get("query_lat", default_lat)),
            format="%.6f",
            key=f"lat-input-{medium}",
        )
    with input_col2:
        lon = st.number_input(
            "Longitude",
            value=float(st.session_state.get("query_lon", default_lon)),
            format="%.6f",
            key=f"lon-input-{medium}",
        )
    with input_col3:
        st.write("")
        st.write("")
        check_button = st.button("Check location", use_container_width=True)

    m = create_base_map(default_lat, default_lon, zoom=10)
    rgba, bounds, metadata = (
        prepare_water_overlay(raster_path)
        if medium == "Water"
        else prepare_raster_overlay(raster_path)
    )
    if rgba is not None and bounds is not None:
        ImageOverlay(
            image=_encode_png(rgba),
            bounds=bounds,
            opacity=0.7,
            name=f"{medium} predicted risk",
            show=True,
        ).add_to(m)
    m.fit_bounds(county_bounds)
    add_map_legend(m, medium)
    folium.LayerControl(collapsed=True, position="topright").add_to(m)
    add_leaflet_internal_css(m)

    map_data = st_folium(
        m,
        width="stretch",
        height=470,
        returned_objects=["last_clicked"],
        key=f"check-location-{medium}",
    )

    clicked = map_data.get("last_clicked") if map_data else None
    if clicked:
        lat = float(clicked["lat"])
        lon = float(clicked["lng"])
        st.session_state["query_lat"] = lat
        st.session_state["query_lon"] = lon

    if not (clicked or check_button):
        st.caption("Click the map or enter coordinates and choose Check location.")
        return

    result = sample_raster_value(raster_path, lat, lon)
    if "error" in result:
        st.warning("No prediction is available at this location.")
        return

    class_label = result.get("risk_label", "Unknown")
    nearest = nearest_sample_context(lat, lon, medium)
    dominant = nearest.get("dominant_metals", "Not available")
    advice = class_advice(medium, class_label)

    result_col1, result_col2 = st.columns(2)
    with result_col1:
        st.metric("Predicted class", class_label)
    with result_col2:
        st.metric("Dominant metals", dominant)

    st.info(advice)

    distance_km = nearest.get("distance_km")
    if distance_km is not None:
        st.caption(
            f"Nearest published {medium.lower()} sample: "
            f"{nearest.get('sample_id', 'N/A')} ({distance_km:.2f} km away)."
        )
        if distance_km > 5.0:
            st.warning("This location is far from any sampled site, so the prediction is less certain.")
        st.caption("Portal uncertainty rule: a location more than 5 km from the nearest published sample is flagged as less certain.")


@st.cache_data(show_spinner=False)
def load_compressed_csv(path_string: str) -> pd.DataFrame:
    """Load a gzip-compressed CSV stored as base64 text in the repository."""
    path = Path(path_string)
    if not path.exists():
        return pd.DataFrame()
    try:
        encoded = path.read_text(encoding="utf-8").strip()
        raw = gzip.decompress(base64.b64decode(encoded))
        return pd.read_csv(io.BytesIO(raw))
    except Exception:
        return pd.DataFrame()


def _rename_and_order_sample_table(df: pd.DataFrame, medium: str) -> pd.DataFrame:
    """Use clear display names and remove duplicate or truncated GIS fields."""
    if df.empty:
        return df

    df = df.drop(columns="geometry", errors="ignore").copy()

    if medium == "Soil":
        rename_map = {
            "LATITUDE": "Latitude",
            "Longitude": "Longitude",
            "Elevation_": "Elevation (m)",
            "Land_use": "Land use",
            "Soil_type": "Soil type",
            "Clay_perce": "Clay (%)",
            "SOC_percen": "SOC (%)",
            "Soil_pH": "Soil pH",
            "Avg_3moths": "Avg 3-month rainfall before data collection (mm)",
            "Avg_3month": "Avg 3-month temperature before data collection (°C)",
            "Distance_f": "Distance from closest road (m)",
            "Distance_1": "Distance from closest mine (m)",
            "Distance_2": "Distance from closest stream (m)",
            "Distance f": "Distance from closest waste disposal (m)",
            "Distance_u": "Distance from closest upstream mine (m)",
            "Distance_3": "Distance from closest upstream waste disposal (m)",
            "Overall_cl": "Overall class",
        }
        preferred = [
            "ID", "Latitude", "Longitude", "Elevation (m)", "Land use", "Soil type",
            "Clay (%)", "SOC (%)", "Soil pH",
            "Avg 3-month rainfall before data collection (mm)",
            "Avg 3-month temperature before data collection (°C)",
            "Distance from closest road (m)",
            "Distance from closest mine (m)",
            "Distance from closest stream (m)",
            "Distance from closest waste disposal (m)",
            "Distance from closest upstream mine (m)",
            "Distance from closest upstream waste disposal (m)",
            "Overall class",
        ]
    else:
        rename_map = {
            "Latitude": "Latitude",
            "Longitude": "Longitude",
            "Elevation_": "Elevation (m)",
            "Land_use": "Land use",
            "Water_type": "Water type",
            "Avg_3month": "Avg 3-month temperature before data collection (°C)",
            "Avg_3mon_1": "Avg 3-month rainfall before data collection (mm)",
            "Distance_f": "Distance from closest waste disposal (m)",
            "Distance_1": "Distance from closest mine (m)",
            "Distance_2": "Distance from closest upstream waste disposal (m)",
            "Distance_3": "Distance from closest upstream mine (m)",
            "Safety_cla": "Safety class",
        }
        df = df.drop(columns=["value"], errors="ignore")
        preferred = [
            "ID", "Latitude", "Longitude", "Elevation (m)", "Land use", "Water type",
            "Avg 3-month temperature before data collection (°C)",
            "Avg 3-month rainfall before data collection (mm)",
            "Distance from closest waste disposal (m)",
            "Distance from closest mine (m)",
            "Distance from closest upstream waste disposal (m)",
            "Distance from closest upstream mine (m)",
            "Safety class",
        ]

    df = df.rename(columns=rename_map)
    df = df[[col for col in preferred if col in df.columns]].copy()

    numeric_cols = df.select_dtypes(include="number").columns
    df[numeric_cols] = df[numeric_cols].round(3)
    return df


def page_data_explorer(uploaded_file, medium: str):
    st.header("Data Explorer")
    st.write("This table lists the published data behind the model.")

    samples = load_sample_points(
        str(SOIL_SAMPLE_POINTS if medium == "Soil" else WATER_SAMPLE_POINTS)
    )
    sample_table = _rename_and_order_sample_table(samples, medium)

    if sample_table.empty:
        st.info(f"No {medium.lower()} sample records are available.")
    else:
        expected = 122 if medium == "Soil" else 89
        st.caption(f"{len(sample_table)} {medium.lower()} sample records (guide total: {expected}).")
        st.dataframe(
            sample_table,
            use_container_width=True,
            hide_index=True,
            height=430,
        )

    st.markdown("---")
    st.subheader("Metal concentrations")

    metal_table = _metal_table_for_medium(medium)
    metals = ["Hg", "As", "Pb", "Cd", "Cr", "Cu", "Zn", "Ni"]
    selected_metal = st.selectbox(
        "Metal",
        metals,
        key=f"metal-select-{medium}",
    )

    unit_suffix = "mg_kg" if medium == "Soil" else "mg_L"
    metal_col = f"{selected_metal}_{unit_suffix}"

    if metal_table.empty or metal_col not in metal_table.columns:
        st.info(f"{selected_metal} results are not available for {medium.lower()}.")
    else:
        display = metal_table[[
            col for col in ["ID", metal_col, "Dominant_Metal", "Overall_class", "Safety_class"]
            if col in metal_table.columns
        ]].copy()
        display = display.rename(columns={
            metal_col: f"{selected_metal} ({'mg/kg' if medium == 'Soil' else 'mg/L'})",
            "Dominant_Metal": "Dominant metal",
            "Overall_class": "Overall class",
            "Safety_class": "Safety class",
        })
        display = display.drop_duplicates()
        value_col = f"{selected_metal} ({'mg/kg' if medium == 'Soil' else 'mg/L'})"
        display[value_col] = pd.to_numeric(display[value_col], errors="coerce")
        display[value_col] = display[value_col].round(5 if medium == "Water" else 4)

        finite = display[value_col].dropna()
        if not finite.empty:
            m1, m2, m3 = st.columns(3)
            m1.metric("Mean", f"{finite.mean():.4g}")
            m2.metric("Maximum", f"{finite.max():.4g}")
            m3.metric("Records", f"{finite.count()}")

        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            height=330,
        )

    st.markdown("---")
    st.subheader("Reference guideline limits")
    limits = load_compressed_csv(str(METAL_LIMITS_TABLE))
    if not limits.empty:
        limit_col = "Soil_limit_mg_kg" if medium == "Soil" else "Water_limit_mg_L"
        guide_table = limits[["Metal", limit_col]].copy()
        guide_table = guide_table.rename(columns={
            limit_col: "CCME soil limit (mg/kg)" if medium == "Soil"
            else "WHO/NEMA water guideline (mg/L)"
        })
        st.dataframe(guide_table, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Raster metadata")
    raster_path = resolve_raster_path(
        medium,
        uploaded_file if medium == "Soil" else None,
    )
    if not raster_path:
        st.warning("Raster data is not available.")
        return

    rgba_image, bounds, metadata = (
        prepare_water_overlay(raster_path)
        if medium == "Water"
        else prepare_raster_overlay(raster_path)
    )
    if metadata.get("error"):
        st.error(metadata["error"])
        return

    c1, c2 = st.columns(2)
    with c1:
        st.write(f"**File:** {Path(raster_path).name}")
        st.write(f"**CRS:** {metadata.get('crs', 'N/A')}")
        st.write(f"**Width:** {metadata.get('width', 'N/A')} px")
        st.write(f"**Height:** {metadata.get('height', 'N/A')} px")
        st.write(f"**NoData:** {metadata.get('nodata', 'N/A')}")
    with c2:
        bounds_obj = metadata.get("bounds")
        if bounds_obj:
            st.write("**Native bounds**")
            st.write(f"- Min X: {bounds_obj['left']:.4f}")
            st.write(f"- Max X: {bounds_obj['right']:.4f}")
            st.write(f"- Min Y: {bounds_obj['bottom']:.4f}")
            st.write(f"- Max Y: {bounds_obj['top']:.4f}")
        if bounds:
            st.write("**WGS84 overlay bounds**")
            st.write(f"- South, West: {bounds[0][0]:.5f}, {bounds[0][1]:.5f}")
            st.write(f"- North, East: {bounds[1][0]:.5f}, {bounds[1][1]:.5f}")


@st.cache_data(show_spinner=False)
def water_feature_importance_table() -> pd.DataFrame:
    try:
        model = joblib.load(WATER_RF_MODEL)
        meta = joblib.load(WATER_FEATURE_META)
        names = list(meta.get("features", []))
        values = list(model.feature_importances_)
        if len(names) != len(values):
            return pd.DataFrame()
        return (
            pd.DataFrame({"Feature": names, "Importance": values})
            .sort_values("Importance", ascending=False)
        )
    except Exception:
        return pd.DataFrame()


def page_model_results(medium: str):
    st.header("Model Results")

    if medium == "Soil":
        st.write(
            "XGBoost was chosen for soil. It reached 76.2% accuracy and a macro F1 of 0.57 "
            "in 5-fold stratified cross-validation on 122 soil samples. It identifies Heavy "
            "contamination well (recall 0.86) but is less reliable for Moderate, Slight and Clean, "
            "which have few samples. The strongest predictors include distance from the closest mine and soil type."
        )

        comparison = pd.DataFrame([
            ["XGBoost (chosen)", "76.2%", 0.57, 0.56, 0.86],
            ["Random Forest", "73.0%", 0.57, 0.58, 0.79],
            ["KNN", "73.8%", 0.53, 0.54, 0.84],
            ["Ordinal logistic regression", "79.5%", 0.44, 0.42, 0.99],
            ["Logistic regression", "39.3%", 0.37, 0.48, 0.36],
        ], columns=["Model", "Accuracy", "Macro F1", "Macro recall", "Heavy recall"])

        per_class = pd.DataFrame([
            ["Clean", 0.67, 0.40, "0.50 (5)"],
            ["Slight contamination", 0.55, 0.60, "0.57 (10)"],
            ["Moderate contamination", 0.32, 0.40, "0.35 (15)"],
            ["Heavy contamination", 0.89, 0.86, "0.87 (92)"],
        ], columns=["Class", "Precision", "Recall", "F1 (samples)"])

        st.subheader("Models comparison")
        st.dataframe(comparison, use_container_width=True, hide_index=True)

        st.subheader("XGBoost per class")
        st.dataframe(per_class, use_container_width=True, hide_index=True)

        chart_col, matrix_col = st.columns([1.15, 1])
        with chart_col:
            st.subheader("Feature importance")
            soil_importance = pd.DataFrame([
                ["Distance from closest mine", 0.148007],
                ["Soil type", 0.126351],
                ["Distance from closest waste disposal", 0.106336],
                ["Clay percent", 0.084425],
                ["Longitude", 0.062403],
                ["3-month temperature", 0.056707],
                ["Distance from closest road", 0.051567],
                ["Latitude", 0.049751],
                ["Upstream waste pit distance", 0.042966],
                ["SOC percent", 0.042614],
                ["Land use", 0.040886],
                ["3-month rainfall", 0.040570],
                ["Soil pH", 0.039696],
                ["Elevation", 0.037968],
                ["Upstream mine distance", 0.036123],
                ["Distance from closest stream", 0.033631],
            ], columns=["Feature", "Importance"])
            st.bar_chart(
                soil_importance.set_index("Feature").sort_values("Importance"),
                horizontal=True,
                height=480,
            )

        with matrix_col:
            st.subheader("Confusion matrix")
            if SOIL_CONFUSION_IMAGE.exists():
                st.image(str(SOIL_CONFUSION_IMAGE), use_container_width=True)

        st.caption("Classified against CCME agriculture soil quality guidelines.")

    else:
        st.write(
            "Random Forest was chosen for water, classed as Safe or Unsafe. It reached 79.8% accuracy "
            "in spatial cross-validation on 89 water samples, correctly identifying 81% of Safe and "
            "78% of Unsafe samples. The strongest predictors are elevation, distance from the closest "
            "waste-disposal site, rainfall and temperature."
        )

        comparison = pd.DataFrame([
            ["Random Forest (chosen)", "79.8%", 0.77, 0.79, 0.78],
            ["XGBoost", "77.5%", 0.74, 0.76, 0.70],
            ["KNN", "69.7%", 0.65, 0.66, 0.56],
            ["Logistic regression", "69.7%", 0.65, 0.66, 0.56],
        ], columns=["Model", "Accuracy", "Macro F1", "Macro recall", "Unsafe recall"])

        per_class = pd.DataFrame([
            ["Safe", 0.89, 0.81, "0.85 (62)"],
            ["Unsafe", 0.64, 0.78, "0.70 (27)"],
        ], columns=["Class", "Precision", "Recall", "F1 (samples)"])

        st.subheader("Models comparison")
        st.dataframe(comparison, use_container_width=True, hide_index=True)

        st.subheader("Random Forest per class")
        st.dataframe(per_class, use_container_width=True, hide_index=True)

        chart_col, matrix_col = st.columns([1.15, 1])
        with chart_col:
            st.subheader("Feature importance")
            importance = water_feature_importance_table()
            if importance.empty:
                st.info(
                    "The saved Random Forest model could not be loaded in this environment. "
                    "The strongest predictors reported by the project are elevation, waste-disposal distance, rainfall and temperature."
                )
            else:
                plot_df = importance.copy()
                plot_df["Feature"] = (
                    plot_df["Feature"]
                    .str.replace("_", " ", regex=False)
                    .str.replace("Avg 3months", "3-month", regex=False)
                )
                st.bar_chart(
                    plot_df.set_index("Feature").sort_values("Importance"),
                    horizontal=True,
                    height=480,
                )

        with matrix_col:
            st.subheader("Confusion matrix")
            if WATER_CONFUSION_IMAGE.exists():
                st.image(str(WATER_CONFUSION_IMAGE), use_container_width=True)

        st.caption("Classified against WHO drinking-water guidelines and NEMA guidelines for zinc.")

    with st.expander("Model artifacts reviewed"):
        if medium == "Soil":
            artifact_rows = [
                ["KNN", "K-nearest soil.ipynb", "soil_contamination_knn_model.pkl"],
                ["Random Forest", "RF soil.ipynb", "soil_contamination_rf_model.pkl"],
                ["XGBoost (chosen)", "XGBOOST soil.ipynb", "soil_contamination_xgb_model.pkl"],
                ["Logistic regression", "logistic regression soil.ipynb", "soil_contamination_logreg_model.pkl"],
                ["Ordinal logistic regression", "ordinal regression soil.ipynb", "soil_contamination_ordinal_logistic.pkl"],
                ["Feature importance", "feature importances soil.ipynb", "—"],
                ["Target encoder", "—", "target_encoder.pkl"],
            ]
        else:
            artifact_rows = [
                ["KNN", "K-nearest water.ipynb", "water_contamination_knn_model.pkl"],
                ["Random Forest (chosen)", "RF water.ipynb", "water_contamination_rf_model.pkl"],
                ["XGBoost", "XGBOOST water.ipynb", "water_contamination_xgb_model.pkl"],
                ["Logistic regression", "logistic regression water.ipynb", "water_contamination_logreg_model.pkl"],
                ["Feature importance", "feature importances water.ipynb", "water_contamination_features.pkl"],
            ]
        artifacts = pd.DataFrame(artifact_rows, columns=["Purpose", "Notebook", "Saved artifact"])
        artifacts["Available"] = artifacts.apply(
            lambda row: "Yes" if (
                (row["Notebook"] == "—" or (ADDITIONAL_DIR / row["Notebook"]).exists())
                and (row["Saved artifact"] == "—" or (ADDITIONAL_DIR / row["Saved artifact"]).exists())
            ) else "Missing",
            axis=1,
        )
        st.dataframe(artifacts, use_container_width=True, hide_index=True)


def page_methodology(medium: str):
    st.header("Methodology")
    st.markdown(
        """
        **Data.** Published soil and water heavy metal data (Hg, As, Pb, Cd, Cr, Cu, Zn, Ni) from
        artisanal gold mining sites in Kakamega County, compiled from peer-reviewed studies.
        No new field sampling was done.

        **Classification.** Soil is classed as Clean, Slight, Moderate or Heavy against CCME soil
        quality guidelines. Water is classed as Safe or Unsafe against WHO drinking-water guidelines
        and NEMA drinking water guidelines for zinc only.

        **Steps.** Compile data, classify, derive GIS predictors (elevation, rainfall, temperature,
        distance to mines and waste sites), train and compare models, choose the best model, validate,
        predict across a grid, build the map.

        **Models.** XGBoost for soil and Random Forest for water. Class imbalance was handled by
        oversampling the training folds only.

        **Validation.** Soil: 5-fold stratified cross-validation. Water: spatial cross-validation.

        **Limitations.** Small samples, strong class imbalance, sampling clustered around known mining
        areas, secondary data only, and some metals (e.g. mercury in water) not measured at some sites.
        """
    )

    if medium == "Soil":
        st.info("Selected medium: Soil · XGBoost · CCME agriculture soil quality guidelines")
    else:
        st.info("Selected medium: Water · Random Forest · WHO drinking-water guidelines and NEMA zinc guideline")

def page_about():
    st.header("About the Project")
    st.markdown(
        """
        **Aim.** To predict and map the spatial distribution of heavy metal contamination in soil and
        water around artisanal gold mining sites in Kakamega County using machine learning.

        **Objectives.**
        1. To identify the environmental and spatial predictors, including distance from mining and
           waste-disposal points, elevation, rainfall, temperature and soil properties, most strongly
           associated with contamination levels.
        2. To develop and validate machine learning models for soil and for water that predict
           contamination levels around artisanal small scale mines in Kakamega county.
        3. To design an interactive map of predicted contamination zones and an accompanying
           application for continuous monitoring.

        **Why it matters.** Heavy metal contamination has been documented at several artisanal gold
        mining sites in Kakamega County, but no study has combined this evidence into one spatially
        continuous assessment. Communities, county authorities and researchers have had no way to
        check contamination risk at a location before deciding on farming, water sourcing or
        mine-site management. This app fills that gap.

        **Study area.** Kakamega County lies in western Kenya, covers about 3,034 km² at 1,240 to
        2,000 m above sea level and forms part of the Lake Victoria Goldfields greenstone belt,
        where artisanal gold mining has taken place since the 1930s.

        **Researcher:** Susan Wambui Mungai, BSc Geology  
        **Supervisor:** Dr. Patrick Gevera  
        **University:** Dedan Kimathi University of Technology

        **Key references.** Ondayo et al. (2023); Meso et al. (2025); King et al. (2024);
        Christine et al. (2018); Omondi & Boitt (2020).
        """
    )

    st.subheader("Study area map")
    county_bounds = get_county_wgs84_bounds()
    center_lat = (county_bounds[0][0] + county_bounds[1][0]) / 2
    center_lon = (county_bounds[0][1] + county_bounds[1][1]) / 2
    m = create_base_map(center_lat, center_lon, zoom=9)
    m.fit_bounds(county_bounds)
    st_folium(m, width="stretch", height=360, returned_objects=[], key="about-study-area")

def page_statistics(medium: str):
    st.header("Key Statistics")

    if medium == "Soil":
        values = [
            ("Samples", "122"),
            ("Metals", "8"),
            ("Classes", "4"),
            ("Model", "XGBoost"),
            ("Accuracy", "76.2%"),
            ("Macro F1", "0.57"),
        ]
        cols = st.columns(3)
        for i, (label, value) in enumerate(values):
            cols[i % 3].metric(label, value)
        if SOIL_CLASS_CHART.exists():
            st.image(str(SOIL_CLASS_CHART), caption="Soil samples per contamination class", use_container_width=True)
    else:
        values = [
            ("Samples evaluated", "89"),
            ("Metals", "8"),
            ("Classes", "2"),
            ("Model", "Random Forest"),
            ("Accuracy", "79.8%"),
            ("Macro F1", "0.77"),
        ]
        cols = st.columns(3)
        for i, (label, value) in enumerate(values):
            cols[i % 3].metric(label, value)
        if WATER_CLASS_CHART.exists():
            st.image(str(WATER_CLASS_CHART), caption="Water samples per class", use_container_width=True)

def page_disclaimer():
    st.header("Disclaimer")
    st.warning(
        """
        Predictions are screening-level estimates from a machine learning model. They are not
        laboratory results and do not replace soil or water testing.

        The soil model is based on 122 published soil samples and the water model on 89 published
        water samples.

        Heavy contamination is predicted most reliably; Moderate, Slight and Clean soil predictions
        are less reliable.

        In water, "Safe" means no tested metal is predicted to exceed WHO drinking-water guidelines.
        Some metals, including mercury, were not measured at some sites and some sampled waters are
        not drinking sources.

        Predictions far from sampled areas are extrapolations and carry more uncertainty.

        The data come from published studies and may not reflect current conditions.
        """
    )

def render_project_header() -> None:
    st.markdown(
        """
        <div class="hero">
            <h1>PREDICTING HEAVY METALS CONTAMINATION AROUND ARTISANAL GOLD MINES IN KAKAMEGA COUNTY</h1>
            <p>An interactive machine learning map showing predicted soil and water contamination risk across Kakamega County, Kenya.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.markdown(get_custom_css(), unsafe_allow_html=True)

    with st.sidebar:
        if LOGO_PATH.exists():
            left, mid, right = st.columns([0.05, 0.9, 0.05])
            with mid:
                st.image(str(LOGO_PATH), width=260)

        st.markdown(
            """
            <div class="brand-block">
                <p class="uni">Dedan Kimathi University of Technology</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            '<p class="nav-label">Navigation Menu</p>'
            '<p style="font-size:0.82rem;color:#b8bbc4;margin:-0.15rem 0 0.35rem 0;">Go to:</p>',
            unsafe_allow_html=True,
        )

        page = st.radio(
            "Navigation",
            [
                "Interactive Map",
                "Check My Location",
                "Data Explorer",
                "Model Results",
                "Methodology",
                "About the Project",
                "Key Statistics",
                "Disclaimer",
            ],
            label_visibility="collapsed",
            index=0,
        )

        st.markdown("#### Soil / Water")
        medium = st.radio(
            "Medium",
            ["Soil", "Water"],
            horizontal=True,
            label_visibility="collapsed",
            key="active_medium",
        )

        if medium == "Soil":
            st.caption("XGBoost · CCME agriculture soil quality guidelines")
        else:
            st.caption("Random Forest · WHO drinking-water guidelines + NEMA zinc guideline")

        with st.expander("Raster file"):
            uploaded = st.file_uploader(
                "Upload GeoTIFF override",
                type=["tif", "tiff"],
                help="Optional GeoTIFF override for the selected map medium.",
            )

        st.markdown("---")
        st.markdown(get_sidebar_footer_html(), unsafe_allow_html=True)

    render_project_header()

    if page == "Interactive Map":
        page_interactive_map(uploaded, medium)
    elif page == "Check My Location":
        page_check_location(uploaded, medium)
    elif page == "Data Explorer":
        page_data_explorer(uploaded, medium)
    elif page == "Model Results":
        page_model_results(medium)
    elif page == "Methodology":
        page_methodology(medium)
    elif page == "About the Project":
        page_about()
    elif page == "Key Statistics":
        page_statistics(medium)
    else:
        page_disclaimer()


if __name__ == "__main__":
    main()
