"""Classic academic styling for the Kakamega WebGIS portal."""


def get_custom_css() -> str:
    return """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&display=swap');

    html, body, [class*="css"], .stApp {
        font-family: "Source Sans 3", "Segoe UI", sans-serif;
        color: #f4f4f5;
    }

    .stApp {
        background: #0e1117;
    }

    .block-container {
        padding-top: 1.15rem;
        padding-bottom: 0.35rem;
        max-width: 1450px;
    }

    iframe[title="streamlit_folium.st_folium"] {
        min-height: 600px;
        border-radius: 10px;
    }

    [data-testid="stHeaderActionElements"],
    [data-testid="stHeadingWithActionElements"] a {
        display: none !important;
    }

    [data-testid="stSidebar"] {
        background: #262730;
        border-right: 1px solid #343640;
    }

    [data-testid="stSidebar"] * {
        color: #f4f4f5 !important;
    }

    [data-testid="stSidebar"] .stRadio label {
        font-size: 0.98rem;
        letter-spacing: 0;
    }

    [data-testid="stSidebar"] hr {
        border-color: #3b3d48;
    }

    .brand-block {
        text-align: center;
        padding: 0.15rem 0.2rem 0.55rem 0.2rem;
        margin-bottom: 0.5rem;
    }

    .brand-block .uni {
        font-family: "Source Sans 3", "Segoe UI", sans-serif;
        font-size: 0.95rem;
        font-weight: 700;
        text-transform: uppercase;
        color: #f4f4f5 !important;
        margin: 0;
        line-height: 1.2;
    }

    .brand-block .dept {
        display: none;
    }

    .nav-label {
        font-size: 1.45rem;
        font-weight: 700;
        letter-spacing: 0;
        text-transform: none;
        color: #f4f4f5 !important;
        margin: 0.45rem 0 0.3rem 0;
    }

    .sidebar-meta {
        background: transparent;
        border: none;
        border-top: 1px solid #3b3d48;
        border-radius: 0;
        padding: 0.8rem 0 0 0;
        margin-top: 0.8rem;
    }

    .sidebar-meta h4 {
        display: none;
    }

    .sidebar-meta p {
        margin: 0.2rem 0;
        font-size: 0.82rem;
        line-height: 1.3;
        color: #d1d5db !important;
    }

    .hero {
        background: transparent;
        color: #f4f4f5;
        padding: 0 !important;
        border-radius: 0;
        border: none;
        margin: 0 0 0.7rem 0;
    }

    .hero h1 {
        font-family: "Source Sans 3", "Segoe UI", sans-serif;
        font-size: 2.25rem !important;
        font-weight: 700;
        color: #ffffff;
        margin: 0 0 0.55rem 0 !important;
        line-height: 1.13;
        max-width: 900px;
    }

    .hero p {
        margin: 0 !important;
        color: #c5c7ce;
        font-size: 1rem !important;
        max-width: 900px;
        line-height: 1.55;
    }

    .map-shell {
        background: transparent;
        border: none;
        border-radius: 10px;
        padding: 0;
        box-shadow: none;
        overflow: hidden;
    }

    .notice {
        background: #252832;
        color: #f4f4f5;
        border-left: 4px solid #ff4b4b;
        padding: 0.65rem 0.8rem;
        font-size: 0.88rem;
        margin: 0.45rem 0 0.7rem 0;
    }

    .page-copy,
    .legend-panel,
    .query-card {
        background: #171a21;
        border: 1px solid #2d3039;
        color: #f4f4f5;
        border-radius: 8px;
    }

    .page-copy h1, .page-copy h2, .page-copy h3,
    .legend-panel h4, .query-card h4 {
        font-family: "Source Sans 3", "Segoe UI", sans-serif;
        color: #ffffff;
    }

    div[data-testid="stMetric"] {
        background: #171a21;
        border: 1px solid #2d3039;
        padding: 0.65rem 0.7rem;
        border-radius: 6px;
    }

    div[data-testid="stButton"] button {
        border-color: #4a4d57;
        background: #171a21;
        color: #ffffff;
    }

    div[data-testid="stRadio"] > div {
        gap: 0;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    """


def get_legend_html(medium: str = "Soil") -> str:
    unit = "class / mg/kg" if medium == "Soil" else "class / mg/L"
    return f"""
    <div class="legend-panel">
        <h4>Risk classification</h4>
        <div class="legend-item"><div class="legend-swatch" style="background:#4CAF50;"></div>Clean</div>
        <div class="legend-item"><div class="legend-swatch" style="background:#FFEB3B;"></div>Slightly contaminated</div>
        <div class="legend-item"><div class="legend-swatch" style="background:#FF9800;"></div>Moderate</div>
        <div class="legend-item"><div class="legend-swatch" style="background:#F44336;"></div>Heavy contamination</div>
        <p style="margin:0.75rem 0 0 0;font-size:0.78rem;color:#5c6770;">
            Overlay classes 1–4 from the prediction raster ({unit}). Click the map to read the value at a point.
        </p>
    </div>
    """


def get_risk_badge_html(risk_category: str) -> str:
    labels = {
        "clean": "Clean",
        "slightly_contaminated": "Slightly contaminated",
        "moderate": "Moderate",
        "heavy": "Heavy contamination",
    }
    label = labels.get(risk_category, risk_category.replace("_", " ").title())
    return f'<span class="risk-badge risk-{risk_category}">{label}</span>'


def get_popup_html(lat: float, lon: float, value: float, risk_category: str, medium: str) -> str:
    unit = "mg/kg" if medium == "Soil" else "mg/L"
    badge = get_risk_badge_html(risk_category)
    return f"""
    <div style="font-family:Georgia, serif; min-width:220px;">
      <div style="border-bottom:2px solid #c4a35a; margin-bottom:8px; padding-bottom:4px;">
        <strong style="color:#152238;">{medium} prediction</strong>
      </div>
      <p style="margin:4px 0;font-family:Segoe UI,sans-serif;font-size:13px;"><b>Latitude:</b> {lat:.6f}</p>
      <p style="margin:4px 0;font-family:Segoe UI,sans-serif;font-size:13px;"><b>Longitude:</b> {lon:.6f}</p>
      <p style="margin:4px 0;font-family:Segoe UI,sans-serif;font-size:13px;"><b>Predicted class / concentration:</b> {value:.3f} {unit}</p>
      <p style="margin:8px 0 0 0;font-family:Segoe UI,sans-serif;font-size:13px;"><b>Risk level:</b> {badge}</p>
    </div>
    """


def get_sidebar_footer_html() -> str:
    return """
    <div class="sidebar-meta">
        <h4>Research team</h4>
        <p><strong>Researcher:</strong> Susan Wambui Mungai</p>
        <p><strong>Course:</strong> BSc Geology</p>
        <p><strong>Supervisor:</strong> Dr. Patrick Gevera</p>
        <p style="margin-top:0.55rem;opacity:0.85;">Dedan Kimathi University of Technology</p>
    </div>
    """
