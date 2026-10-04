import base64
import io
from pathlib import Path

import folium
import streamlit as st
from folium.plugins import Fullscreen, LocateControl, MousePosition
from folium.raster_layers import ImageOverlay
from PIL import Image
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
</style>
""", unsafe_allow_html=True)


def _encode_png(rgba_image) -> str:
    img = Image.fromarray(rgba_image)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


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
    return m


def add_raster_overlay(m: folium.Map, raster_path: str, opacity: float, layer_name: str):
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


def add_map_legend(m: folium.Map) -> None:
    legend = """
    <div style="position:fixed;bottom:28px;right:12px;z-index:999;
                background:rgba(255,255,255,0.94);padding:10px 12px;
                border:1px solid #c4a35a;font-family:Georgia,serif;font-size:12px;
                color:#152238;min-width:168px;box-shadow:0 2px 8px rgba(21,34,56,0.18);">
      <div style="font-weight:700;margin-bottom:6px;border-bottom:1px solid #c4a35a;padding-bottom:4px;">Risk classification</div>
      <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#4CAF50;border:1px solid #333;margin-right:6px;"></span>Clean</div>
      <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FFEB3B;border:1px solid #333;margin-right:6px;"></span>Slightly contaminated</div>
      <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#FF9800;border:1px solid #333;margin-right:6px;"></span>Moderate</div>
      <div style="margin:4px 0;"><span style="display:inline-block;width:12px;height:12px;background:#F44336;border:1px solid #333;margin-right:6px;"></span>Heavy contamination</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))


def render_click_marker(m: folium.Map, click: dict, raster_path: str, medium: str):
    lat, lon = click["lat"], click["lng"]
    result = sample_raster_value(raster_path, lat, lon)
    if "error" not in result:
        unit = "mg/kg" if medium == "Soil" else "mg/L"
        popup_html = f"""
        <div style="background: {result['color']}; color: white; padding: 12px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
            <strong style="font-size: 1.1em;">📍 Location Details</strong><br>
            <span style="font-size: 0.95em;">Latitude: {lat:.6f}</span><br>
            <span style="font-size: 0.95em;">Longitude: {lon:.6f}</span><br>
            <span style="font-size: 0.95em;">Concentration: {result['value']:.3f} {unit}</span><br>
            <span style="font-size: 0.95em;">Risk Level: {result['risk_label']}</span>
        </div>
        """
        popup = folium.Popup(popup_html, max_width=300)
        folium.CircleMarker(
            location=[lat, lon],
            radius=8,
            color="#152238",
            weight=2,
            fill=True,
            fill_color=result["color"],
            fill_opacity=0.95,
            popup=popup,
        ).add_to(m)
    else:
        popup = folium.Popup(f"<div style='padding: 8px;'>{result['error']}</div>", max_width=250)
        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            color="#152238",
            fill=True,
            fill_color="#ffffff",
            popup=popup,
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

    ctrl_left, ctrl_mid, ctrl_right = st.columns([1.1, 0.8, 1.6])
    with ctrl_left:
        medium = st.radio(
            "Medium",
            ["Soil", "Water"],
            horizontal=True,
            help="Soil uses the training prediction raster. Water currently uses generated sample classes until the real water raster is provided.",
        )
    with ctrl_mid:
        center_button = st.button("Center to Raster", help="Zoom and center the map to fit the raster extent")
    with ctrl_right:
        opacity = st.slider("Raster opacity", min_value=0.1, max_value=1.0, value=0.7, step=0.05)

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

    # Check if center button was clicked
    if center_button:
        st.session_state.center_to_raster = True

    # Get zoom level from session state if available
    zoom_level = st.session_state.get("map_zoom", 10)
    if st.session_state.get("center_to_raster", False):
        zoom_level = 11  # Zoom in when centering
        st.session_state.center_to_raster = False

    m = create_base_map(center_lat, center_lon, zoom=zoom_level)
    overlay, metadata, bounds = add_raster_overlay(
        m,
        raster_path,
        opacity,
        layer_name=f"{medium} contamination risk",
    )
    if overlay is None:
        st.error(f"Failed to load raster overlay: {metadata.get('error', 'Unknown error')}")
        return

    # Always fit to raster bounds on initial load or when centering
    if center_button or 'map_loaded' not in st.session_state:
        m.fit_bounds(bounds)
        st.session_state.map_loaded = True

    add_map_legend(m)
    folium.LayerControl(collapsed=True, position="topright").add_to(m)

    # Add marker if there was a previous click
    if 'last_click' in st.session_state:
        click_data = st.session_state['last_click']
        if click_data.get('medium') == medium:
            render_click_marker(m, click_data, raster_path, medium)

    st.markdown('<div class="map-shell">', unsafe_allow_html=True)
    map_data = st_folium(
        m,
        width="stretch",
        height=600,
        returned_objects=["last_clicked", "zoom"],
        key=f"kakamega-map-{medium}",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # Store zoom level in session state
    if map_data and "zoom" in map_data:
        st.session_state.map_zoom = map_data["zoom"]

    # Handle click - store in session state to trigger marker on next render
    clicked = map_data.get("last_clicked") if map_data else None
    if clicked:
        st.session_state['last_click'] = clicked
        st.session_state['last_click']['medium'] = medium
        st.rerun()
    else:
        # Clear click if user clicked elsewhere or changed medium
        if 'last_click' in st.session_state:
            if st.session_state['last_click'].get('medium') != medium:
                del st.session_state['last_click']


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
            left, mid, right = st.columns([1, 2, 1])
            with mid:
                st.image(str(LOGO_PATH), width=96)
        st.markdown(
            """
            <div class="brand-block">
                <p class="uni">Dedan Kimathi University of Technology</p>
                <p class="dept">Department of Geosciences</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<p class="nav-label">Navigation</p>', unsafe_allow_html=True)
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
