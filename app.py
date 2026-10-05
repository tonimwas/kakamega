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
    ensure_water_sample_raster,
    get_raster_src,
    is_sample_raster,
    prepare_raster_overlay,
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
WATER_RASTER = ROOT / "data" / "Raster" / "Water_sample.tif"
WATER_RASTER_LEGACY = ROOT / "data" / "Raster" / "Water_sample_raster.tif"
LOGO_PATH = ROOT / "assets" / "logo.png"
UPLOAD_DIR = ROOT / "data" / "Raster" / "uploads"
VECTOR_DIR = ROOT / "data" / "vector"
WARDS_GEOJSON = VECTOR_DIR / "Wards.geojson"
CONSTITUENCIES_GEOJSON = VECTOR_DIR / "Constituencies.geojson"
COUNTY_GEOJSON = VECTOR_DIR / "KakamegaCounty.geojson"

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
    .leaflet-top.leaflet-right .leaflet-control-layers {
        margin-top: 52px !important;
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


def add_instant_raster_click(m: folium.Map, rgba_image, bounds) -> None:
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

            const classes = [
                {rgb: [76, 175, 80], label: "Clean"},
                {rgb: [255, 235, 59], label: "Slightly contaminated"},
                {rgb: [255, 152, 0], label: "Moderate"},
                {rgb: [244, 67, 54], label: "Heavy contamination"}
            ];

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
                    <strong style="font-size: 12px; color: black;">Contamination: ${risk.label}</strong><br>
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

    for candidate in (WATER_RASTER, WATER_RASTER_LEGACY):
        if candidate.exists():
            return str(candidate)
    if not SOIL_RASTER.exists():
        return None
    return ensure_water_sample_raster(str(SOIL_RASTER), str(WATER_RASTER))


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


def add_raster_overlay(m: folium.Map, raster_path: str, opacity: float, layer_name: str):
    rgba_image, bounds, metadata = prepare_raster_overlay(raster_path)
    if rgba_image is None or bounds is None:
        return None, metadata, None

    overlay = ImageOverlay(
        image=_encode_png(rgba_image),
        bounds=bounds,
        opacity=0.7,
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
                panel.style.background = "rgba(20,20,20,0.18)";
                panel.style.backdropFilter = "blur(2px)";

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


def add_map_legend(m: folium.Map) -> None:
    legend = """
    <div style="position:fixed;bottom:28px;left:12px;z-index:999;
                background:rgba(255,255,255,0.94);padding:10px 12px;
                border:1px solid #c4a35a;font-family:Georgia,serif;font-size:12px;
                color:#152238;min-width:168px;box-shadow:0 2px 8px rgba(21,34,56,0.18);">
      <div style="font-weight:700;margin-bottom:6px;border-bottom:1px solid #c4a35a;padding-bottom:4px;">Contamination risk</div>
      <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#4CAF50;border:1px solid #333;margin-right:6px;"></span>Clean</div>
      <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FFEB3B;border:1px solid #333;margin-right:6px;"></span>Slightly contaminated</div>
      <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FF9800;border:1px solid #333;margin-right:6px;"></span>Moderate</div>
      <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#F44336;border:1px solid #333;margin-right:6px;"></span>Heavy contamination</div>
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
            <p style="font-size: 0.85rem; margin: 0;">An interactive machine learning map showing predicted soil and water contamination risk across Kakamega County, Kenya.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    medium = st.radio(
        "Medium",
        ["Soil", "Water"],
        horizontal=True,
        help="Soil uses the training prediction raster. Water currently uses generated sample classes until the real water raster is provided.",
    )

    raster_path = resolve_raster_path(medium, uploaded_file)
    if raster_path is None:
        st.error("No soil raster found at `data/Raster/Training_raster.tif`. Upload a GeoTIFF in the sidebar to continue.")
        return

    if medium == "Water" and is_sample_raster(raster_path):
        st.markdown(
            '<div class="notice"><b>Water layer is placeholder data.</b> '
            "A sample raster was generated on the soil grid so the map tools can be tested. "
            "Replace <code>data/Raster/Water_sample.tif</code> (or <code>Water_sample_raster.tif</code>) with the real water prediction when it is ready.</div>",
            unsafe_allow_html=True,
        )

    try:
        center_lat, center_lon = raster_map_center(raster_path)
    except Exception:
        center_lat, center_lon = 0.28, 34.75

    m = create_base_map(center_lat, center_lon, zoom=10)
    rgba_image, bounds, metadata = prepare_raster_overlay(raster_path)
    if rgba_image is None or bounds is None:
        st.error(f"Failed to load raster overlay: {metadata.get('error', 'Unknown error')}")
        return

    overlay = ImageOverlay(
        image=_encode_png(rgba_image),
        bounds=bounds,
        opacity=opacity,
        name=f"{medium} contamination risk",
        interactive=False,
        cross_origin=False,
        zindex=1,
    )
    overlay.add_to(m)
    # Initial map extent. Later centering is handled instantly in Leaflet.
    m.fit_bounds(bounds)

    add_map_controls(m, overlay, bounds, initial_opacity=0.7)
    add_map_legend(m)
    folium.LayerControl(collapsed=True, position="topright").add_to(m)

    # Handle raster identification entirely in the browser for instant popups.
    add_instant_raster_click(m, rgba_image, bounds)

    st.markdown('<div class="map-shell">', unsafe_allow_html=True)
    st_folium(
        m,
        width="stretch",
        height=600,
        returned_objects=[],
        key=f"kakamega-map-{medium}",
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
        add_raster_overlay(m, raster_path, 0.7, "Soil contamination risk")
        add_map_legend(m)
        folium.LayerControl().add_to(m)
    else:
        m = create_base_map(0.28, 34.75)
        folium.LayerControl().add_to(m)

    st_folium(m, width="stretch", height=650, returned_objects=[])


def page_data_explorer(uploaded_file):
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("Data explorer")
    st.write("Metadata for the active prediction raster. Soil is the observed training raster; water is sample-generated until replaced.")
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
        if is_sample_raster(raster_path):
            st.warning("This file is tagged as generated sample data.")
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


def page_model_results():
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("Model results")
    st.write("Summary of the prediction used by this map portal.")
    st.markdown(
        """
        - **Model type:** Random Forest classifier / spatial prediction
        - **Mapped medium (available):** Soil
        - **Mapped medium (placeholder):** Water
        - **Output:** Four risk classes (1 Clean – 4 Heavy contamination)
        - **Display CRS:** EPSG:4326 for the web map; sampling is performed in the raster native CRS (UTM zone 37S / EPSG:32737 for the current soil grid)
        """
    )
    st.markdown("</div>", unsafe_allow_html=True)


def page_methodology():
    st.markdown('<div class="page-copy" style="padding: 0.3rem 0;">', unsafe_allow_html=True)
    st.header("Methodology")
    st.subheader("Data collection")
    st.write("Soil samples were collected around artisanal gold mining sites in Kakamega County. Water predictions will use the same mapping grid when that raster is supplied.")
    st.subheader("Prediction and mapping")
    st.write("A machine-learning surface was interpolated / classified and stored as a GeoTIFF. The portal reprojects that grid to WGS84 only for display.")
    st.subheader("Risk classification")
    st.markdown(
        """
        The current soil raster is a four-class map:

        | Class | Risk |
        | --- | --- |
        | 1 | Clean |
        | 2 | Slightly contaminated |
        | 3 | Moderate |
        | 4 | Heavy contamination |
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
        "It is not a substitute for laboratory analysis, site inspection, or official environmental assessment. "
        "The water overlay is sample-generated until the real water raster is installed."
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
                help="Used if the bundled soil raster is missing, or to override it.",
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
