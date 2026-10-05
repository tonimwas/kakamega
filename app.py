import base64
import io
import json
from pathlib import Path

import folium
import geopandas as gpd
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
        height: 100vh;
        overflow: hidden;
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

    /* Keep the expanded Leaflet layer control beside the zoom buttons. */
    .leaflet-top.leaflet-left .leaflet-control-layers {
        position: absolute !important;
        left: 44px !important;
        top: 0 !important;
        margin: 10px 0 0 0 !important;
        min-width: 175px;
        max-height: 220px;
        overflow-y: auto;
        background: rgba(255,255,255,0.94);
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
                    'color': '#808080',
                    'weight': 0.5,
                    'fillOpacity': 0.0,
                },
            ).add_to(wards_layer)
            wards_layer.add_to(m)
        except Exception as e:
            pass

    # Add Constituencies layer
    if CONSTITUENCIES_GEOJSON.exists():
        try:
            constituencies_layer = folium.FeatureGroup(name="Constituencies")
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
    """Load sample points in WGS84 for map display and Data Explorer tables."""
    path = Path(path_string)
    if not path.exists():
        return gpd.GeoDataFrame()

    gdf = gpd.read_file(path)
    if gdf.crs is not None and str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


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
        return "#2196F3"
    if text == "unsafe":
        return "#FFEB3B"
    return "#9E9E9E"


def add_sample_point_layers(m: folium.Map):
    """Add hidden soil and water sample layers with class-matched symbols."""
    soil_layer = folium.FeatureGroup(
        name="Soil sample points",
        show=False,
        control=False,
    )
    water_layer = folium.FeatureGroup(
        name="Water sample points",
        show=False,
        control=False,
    )

    soil_gdf = load_sample_points(str(SOIL_SAMPLE_POINTS))
    if not soil_gdf.empty:
        for _, row in soil_gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            sample_id = row.get("ID", "")
            category = row.get("Overall_cl", "")
            popup = (
                "<div style='font-size:12px;color:#111;'>"
                f"<strong>Soil sample: {sample_id}</strong><br>"
                f"<strong>Class:</strong> {category}"
                "</div>"
            )
            folium.CircleMarker(
                location=[float(geom.y), float(geom.x)],
                radius=5,
                color="#FFFFFF",
                weight=1.2,
                fill=True,
                fill_color=_soil_sample_color(category),
                fill_opacity=0.95,
                popup=folium.Popup(popup, max_width=260),
            ).add_to(soil_layer)

    water_gdf = load_sample_points(str(WATER_SAMPLE_POINTS))
    if not water_gdf.empty:
        for _, row in water_gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            sample_id = row.get("ID", "")
            category = row.get("Safety_cla", "")
            popup = (
                "<div style='font-size:12px;color:#111;'>"
                f"<strong>Water sample: {sample_id}</strong><br>"
                f"<strong>Safety:</strong> {category}"
                "</div>"
            )
            folium.CircleMarker(
                location=[float(geom.y), float(geom.x)],
                radius=5,
                color="#FFFFFF",
                weight=1.2,
                fill=True,
                fill_color=_water_sample_color(category),
                fill_opacity=0.95,
                popup=folium.Popup(popup, max_width=260),
            ).add_to(water_layer)

    soil_layer.add_to(m)
    water_layer.add_to(m)
    return soil_layer, water_layer


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
        name="Esri World Imagery",
        overlay=False,
        control=True,
        show=True,
    ).add_to(m)

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Esri, HERE, Garmin, USGS, Intermap, INCREMENT P, NRCan, METI, and the GIS User Community",
        name="Esri World Street Map",
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


def add_map_controls(
    m: folium.Map,
    overlay: ImageOverlay,
    bounds,
    initial_opacity: float = 0.7,
) -> None:
    """Add browser-only center and opacity controls without Streamlit reruns."""
    south, west = bounds[0]
    north, east = bounds[1]

    template = """
    {% macro script(this, kwargs) %}
    (function() {
        const map = {{ this._parent.get_name() }};
        const overlay = __OVERLAY_NAME__;
        const rasterBounds = L.latLngBounds(
            [__SOUTH__, __WEST__],
            [__NORTH__, __EAST__]
        );

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
            options: { position: "topleft" },
            onAdd: function() {
                const container = L.DomUtil.create(
                    "div",
                    "leaflet-bar kakamega-center-control"
                );
                const button = L.DomUtil.create("a", "", container);
                button.href = "#";
                button.title = "Center to raster";
                button.setAttribute("aria-label", "Center to raster");
                button.innerHTML = "⌖";
                button.style.fontSize = "22px";
                button.style.fontWeight = "700";
                button.style.lineHeight = "30px";
                button.style.textAlign = "center";
                button.style.width = "30px";
                button.style.height = "30px";
                button.style.color = "#222";
                button.style.background = "rgba(255,255,255,0.90)";

                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.on(button, "click", function(e) {
                    L.DomEvent.preventDefault(e);
                    map.fitBounds(rasterBounds, {
                        animate: true,
                        duration: 0.25,
                        padding: [8, 8]
                    });
                });
                return container;
            }
        });
        map.addControl(new CenterControl());

        const OpacityControl = L.Control.extend({
            options: { position: "topright" },
            onAdd: function() {
                const container = L.DomUtil.create(
                    "div",
                    "kakamega-opacity-control"
                );
                container.style.background = "transparent";
                container.style.border = "none";
                container.style.boxShadow = "none";
                container.style.padding = "0";
                container.style.margin = "8px 10px 0 0";

                const panel = L.DomUtil.create("div", "", container);
                panel.style.display = "flex";
                panel.style.alignItems = "center";
                panel.style.gap = "7px";
                panel.style.padding = "4px 7px";
                panel.style.borderRadius = "8px";
                panel.style.background = "transparent";
                panel.style.backdropFilter = "none";

                const icon = L.DomUtil.create("span", "", panel);
                icon.innerHTML = "◐";
                icon.title = "Raster transparency";
                icon.style.color = "#fff";
                icon.style.fontSize = "17px";
                icon.style.textShadow = "0 1px 2px rgba(0,0,0,0.65)";

                const slider = L.DomUtil.create("input", "", panel);
                slider.type = "range";
                slider.min = "0.10";
                slider.max = "1.00";
                slider.step = "0.05";
                slider.value = "__INITIAL_OPACITY__";
                slider.title = "Raster transparency";
                slider.setAttribute("aria-label", "Raster transparency");
                slider.style.width = "105px";
                slider.style.margin = "0";
                slider.style.cursor = "pointer";
                slider.style.accentColor = "#ffffff";

                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.disableScrollPropagation(container);

                slider.addEventListener("input", function() {
                    overlay.setOpacity(parseFloat(slider.value));
                });

                return container;
            }
        });
        map.addControl(new OpacityControl());
    })();
    {% endmacro %}
    """

    replacements = {
        "__OVERLAY_NAME__": overlay.get_name(),
        "__SOUTH__": repr(float(south)),
        "__WEST__": repr(float(west)),
        "__NORTH__": repr(float(north)),
        "__EAST__": repr(float(east)),
        "__INITIAL_OPACITY__": f"{float(initial_opacity):.2f}",
    }
    for token, value in replacements.items():
        template = template.replace(token, value)

    controls = MacroElement()
    controls._name = "RasterMapControls"
    controls._template = Template(template)
    m.add_child(controls)


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
            {rgb: [33, 150, 243], label: "Safe"},
            {rgb: [255, 235, 59], label: "Unsafe"}
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
                    '<div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#2196F3;border:1px solid #333;margin-right:6px;"></span>Safe</div>' +
                    '<div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FFEB3B;border:1px solid #333;margin-right:6px;"></span>Unsafe</div>';
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

        const MediumControl = L.Control.extend({
            options: {position: "topleft"},
            onAdd: function() {
                const container = L.DomUtil.create("div", "leaflet-bar");
                container.style.display = "flex";
                container.style.marginTop = "8px";
                ["Soil", "Water"].forEach(name => {
                    const btn = L.DomUtil.create("a", "kakamega-medium-btn", container);
                    btn.href = "#";
                    btn.dataset.medium = name;
                    btn.innerHTML = name;
                    btn.style.width = "54px";
                    btn.style.height = "30px";
                    btn.style.lineHeight = "30px";
                    btn.style.textAlign = "center";
                    btn.style.fontSize = "12px";
                    btn.style.fontWeight = "600";
                    L.DomEvent.on(btn, "click", function(e) {
                        L.DomEvent.preventDefault(e);
                        setMedium(name);
                    });
                });
                L.DomEvent.disableClickPropagation(container);
                return container;
            }
        });
        map.addControl(new MediumControl());

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

        setMedium("Soil");
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
          <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#2196F3;border:1px solid #333;margin-right:6px;"></span>Safe</div>
          <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FFEB3B;border:1px solid #333;margin-right:6px;"></span>Unsafe</div>
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


def page_interactive_map(uploaded_file):
    st.markdown(
        """
        <div class="hero" style="padding: 0.3rem 0;">
            <h1 style="font-size: 1.3rem; margin: 0.2rem 0;">Predicting heavy metal contamination around artisanal gold mines in Kakamega County</h1>
            <p style="font-size: 0.85rem; margin: 0;">An interactive machine learning map showing predicted soil contamination and water safety across Kakamega County, Kenya.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    soil_path = str(SOIL_RASTER) if SOIL_RASTER.exists() else None
    water_path = str(WATER_RASTER) if WATER_RASTER.exists() else None

    if soil_path is None or water_path is None:
        st.error("Both soil and water raster files are required in data/Raster.")
        return

    try:
        center_lat, center_lon = raster_map_center(soil_path)
    except Exception:
        center_lat, center_lon = 0.28, 34.75

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
        name="Soil contamination risk",
        interactive=False,
        cross_origin=False,
        zindex=1,
        show=True,
    )
    soil_overlay.add_to(m)

    water_overlay = ImageOverlay(
        image=_encode_png(water_rgba),
        bounds=water_bounds,
        opacity=0.7,
        name="Water safety",
        interactive=False,
        cross_origin=False,
        zindex=1,
        show=False,
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
    )

    folium.LayerControl(collapsed=False, position="topleft").add_to(m)

    st.markdown('<div class="map-shell">', unsafe_allow_html=True)
    st_folium(
        m,
        width="stretch",
        height=600,
        returned_objects=[],
        key="kakamega-map",
    )
    st.markdown("</div>", unsafe_allow_html=True)


def page_check_location(uploaded_file):
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("Check my location")
    st.write("Use the locate control on the map to centre on your GPS position, then inspect the overlay.")
    st.markdown("</div>", unsafe_allow_html=True)

    raster_path = resolve_raster_path("Soil", uploaded_file)
    if raster_path and Path(raster_path).exists():
        center_lat, center_lon = raster_map_center(raster_path)
        m = create_base_map(center_lat, center_lon, zoom=11)
        add_raster_overlay(m, raster_path, 0.7, "Soil contamination risk", medium="Soil")
        add_map_legend(m)
        folium.LayerControl().add_to(m)
    else:
        m = create_base_map(0.28, 34.75)
        folium.LayerControl().add_to(m)

    st_folium(m, width="stretch", height=650, returned_objects=[])


def page_data_explorer(uploaded_file):
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("Data explorer")
    st.write("Metadata for the active soil or water prediction raster.")
    st.markdown("</div>", unsafe_allow_html=True)

    medium = st.radio("Raster", ["Soil", "Water"], horizontal=True)
    raster_path = resolve_raster_path(medium, uploaded_file if medium == "Soil" else None)
    if not raster_path:
        st.warning("Raster data is not available.")
        return

    rgba_image, bounds, metadata = prepare_raster_overlay(raster_path)
    if metadata.get("error"):
        st.error(metadata["error"])
        return

    c1, c2 = st.columns(2)
    with c1:
        st.write(f"**File:** `{Path(raster_path).name}`")
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

    st.markdown("---")
    st.subheader("Sample points")

    soil_tab, water_tab = st.tabs(["Soil samples", "Water samples"])

    with soil_tab:
        soil_samples = load_sample_points(str(SOIL_SAMPLE_POINTS))
        if soil_samples.empty:
            st.info("No soil sample points are available.")
        else:
            soil_table = soil_samples.drop(columns="geometry", errors="ignore").copy()
            soil_table = soil_table.rename(
                columns={
                    "LATITUDE": "Latitude",
                    "Longitude": "Longitude",
                    "Elevation_": "Elevation",
                    "Land_use": "Land use",
                    "Soil_type": "Soil type",
                    "Clay_perce": "Clay (%)",
                    "SOC_percen": "SOC (%)",
                    "Soil_pH": "Soil pH",
                    "Overall_cl": "Contamination class",
                }
            )
            numeric_cols = soil_table.select_dtypes(include="number").columns
            soil_table[numeric_cols] = soil_table[numeric_cols].round(3)
            preferred = [
                "ID", "Latitude", "Longitude", "Elevation", "Land use",
                "Soil type", "Clay (%)", "SOC (%)", "Soil pH",
                "Contamination class",
            ]
            remaining = [col for col in soil_table.columns if col not in preferred]
            soil_table = soil_table[[col for col in preferred if col in soil_table.columns] + remaining]
            st.caption(f"{len(soil_table)} soil sample points")
            st.dataframe(
                soil_table,
                use_container_width=True,
                hide_index=True,
                height=420,
            )

    with water_tab:
        water_samples = load_sample_points(str(WATER_SAMPLE_POINTS))
        if water_samples.empty:
            st.info("No water sample points are available.")
        else:
            water_table = water_samples.drop(columns="geometry", errors="ignore").copy()
            water_table = water_table.rename(
                columns={
                    "Latitude": "Latitude",
                    "Longitude": "Longitude",
                    "Elevation_": "Elevation",
                    "Land_use": "Land use",
                    "Water_type": "Water type",
                    "Safety_cla": "Safety class",
                    "value": "Class value",
                }
            )
            numeric_cols = water_table.select_dtypes(include="number").columns
            water_table[numeric_cols] = water_table[numeric_cols].round(3)
            preferred = [
                "ID", "Latitude", "Longitude", "Elevation", "Land use",
                "Water type", "Safety class", "Class value",
            ]
            remaining = [col for col in water_table.columns if col not in preferred]
            water_table = water_table[[col for col in preferred if col in water_table.columns] + remaining]
            st.caption(f"{len(water_table)} water sample points")
            st.dataframe(
                water_table,
                use_container_width=True,
                hide_index=True,
                height=420,
            )


def page_model_results():
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("Model results")
    st.write("Summary of the prediction used by this map portal.")
    st.markdown(
        """
        - **Model type:** Random Forest classifier / spatial prediction
        - **Mapped media:** Soil and Water
        - **Soil output:** Four classes (1 Clean – 4 Heavy contamination)
        - **Water output:** Two classes (1 Safe, 2 Unsafe)
        - **Display CRS:** EPSG:4326 for the web map; sampling is performed in the raster native CRS (UTM zone 37S / EPSG:32737 for the current soil grid)
        """
    )
    st.markdown("</div>", unsafe_allow_html=True)


def page_methodology():
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("Methodology")
    st.subheader("Data collection")
    st.write("Soil and water samples were assessed around artisanal gold mining sites in Kakamega County and mapped as classified prediction rasters.")
    st.subheader("Prediction and mapping")
    st.write("A machine-learning surface was interpolated / classified and stored as a GeoTIFF. The portal reprojects that grid to WGS84 only for display.")
    st.subheader("Risk classification")
    st.markdown(
        """
        The soil raster uses four contamination classes, while the water raster uses two safety classes:

        | Medium | Class | Category |
        | --- | --- | --- |
        | Soil | 1 | Clean |
        | Soil | 2 | Slightly contaminated |
        | Soil | 3 | Moderate |
        | Soil | 4 | Heavy contamination |
        | Water | 1 | Safe |
        | Water | 2 | Unsafe |
        """
    )
    st.markdown("</div>", unsafe_allow_html=True)


def page_about():
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("About the project")
    st.write(
        "Artisanal gold mining in Kakamega County has raised concerns about heavy metal "
        "contamination of soils and water. This portal publishes the spatial prediction so that "
        "a location can be queried without desktop GIS software."
    )
    st.markdown("</div>", unsafe_allow_html=True)


def page_statistics():
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("Key statistics")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("County area (approx.)", "3,224 km²")
    c2.metric("Soil grid size", "884 × 695")
    c3.metric("Cell size", "100 m")
    c4.metric("Risk classes", "4")
    st.caption("Grid statistics are read from the soil GeoTIFF currently in `data/Raster/Training_raster.tif`.")
    st.markdown("</div>", unsafe_allow_html=True)


def page_disclaimer():
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("Disclaimer")
    st.warning(
        "This application shows predicted contamination risk from a research model. "
        "It is not a substitute for laboratory analysis, site inspection, or official environmental assessment."
    )
    st.markdown("</div>", unsafe_allow_html=True)


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
                <p class="dept">Department of Geosciences</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<p class="nav-label">Navigation Menu</p><p style="font-size:0.82rem;color:#b8bbc4;margin:-0.15rem 0 0.35rem 0;">Go to:</p>', unsafe_allow_html=True)
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
        with st.expander("Raster file"):
            uploaded = st.file_uploader(
                "Upload GeoTIFF override",
                type=["tif", "tiff"],
                help="Optional GeoTIFF override for the selected map medium.",
            )
        st.markdown("---")
        st.markdown(get_sidebar_footer_html(), unsafe_allow_html=True)

    if page == "Interactive Map":
        page_interactive_map(uploaded)
    elif page == "Check My Location":
        page_check_location(uploaded)
    elif page == "Data Explorer":
        page_data_explorer(uploaded)
    elif page == "Model Results":
        page_model_results()
    elif page == "Methodology":
        page_methodology()
    elif page == "About the Project":
        page_about()
    elif page == "Key Statistics":
        page_statistics()
    else:
        page_disclaimer()


if __name__ == "__main__":
    main()
