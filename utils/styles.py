"""Classic academic styling for the Kakamega WebGIS portal."""


def get_custom_css() -> str:
    return """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Source+Sans+3:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: "Source Sans 3", "Segoe UI", sans-serif;
        color: #1f2933;
    }

    .stApp {
        background: #f4f1ea;
    }

    .block-container {
        padding-top: 0.3rem;
        padding-bottom: 0.3rem;
        max-width: 1480px;
    }

    iframe[title="streamlit_folium.st_folium"] {
        min-height: 600px;
    }

    [data-testid="stHeaderActionElements"],
    [data-testid="stHeadingWithActionElements"] a {
        display: none !important;
    }

    [data-testid="stSidebar"] {
        background: #152238;
        border-right: 1px solid #c4a35a;
    }

    [data-testid="stSidebar"] * {
        color: #f4f1ea !important;
    }

    [data-testid="stSidebar"] .stRadio label {
        font-size: 0.92rem;
        letter-spacing: 0.01em;
    }

    [data-testid="stSidebar"] hr {
        border-color: rgba(196, 163, 90, 0.35);
    }

    .brand-block {
        text-align: center;
        padding: 0.15rem 0.2rem 0.7rem 0.2rem;
        border-bottom: 1px solid rgba(196, 163, 90, 0.4);
        margin-bottom: 0.55rem;
    }

    .brand-block img {
        max-width: 86px;
        margin: 0 auto 0.4rem auto;
        display: block;
        background: #fff;
        border-radius: 6px;
        padding: 4px;
    }

    .brand-block .uni {
        font-family: "Cormorant Garamond", Georgia, serif;
        font-size: 1.15rem;
        font-weight: 700;
        color: #e8d7a3 !important;
        margin: 0;
        line-height: 1.25;
    }

    .brand-block .dept {
        font-size: 0.75rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #c9d3df !important;
        margin: 0.35rem 0 0 0;
    }

    .nav-label {
        font-size: 0.72rem;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: #c4a35a !important;
        margin: 0.4rem 0 0.6rem 0;
    }

    .sidebar-meta {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(196, 163, 90, 0.28);
        border-radius: 8px;
        padding: 0.85rem 0.9rem;
        margin-top: 0.5rem;
    }

    .sidebar-meta h4 {
        font-family: "Cormorant Garamond", Georgia, serif;
        margin: 0 0 0.45rem 0;
        color: #e8d7a3 !important;
        font-size: 1.05rem;
    }

    .sidebar-meta p {
        margin: 0.18rem 0;
        font-size: 0.8rem;
        line-height: 1.35;
        color: #dbe4ee !important;
    }

    .hero {
        background: linear-gradient(180deg, #1b3358 0%, #152238 100%);
        color: #f7f3ea;
        padding: 0.5rem 0.9rem 0.4rem 0.9rem;
        border-radius: 8px;
        border-bottom: 3px solid #c4a35a;
        margin-bottom: 0.5rem;
    }

    .hero h1 {
        font-family: "Cormorant Garamond", Georgia, serif;
        font-size: 1.4rem;
        font-weight: 700;
        color: #fff;
        margin: 0 0 0.2rem 0;
        line-height: 1.2;
    }

    .hero p {
        margin: 0;
        color: #d5deea;
        font-size: 0.9rem;
        max-width: 78ch;
    }

    .toolbar {
        background: #fff;
        border: 1px solid #ddd4c4;
        border-radius: 8px;
        padding: 0.5rem 0.7rem 0.3rem 0.7rem;
        margin-bottom: 0.5rem;
        box-shadow: 0 1px 2px rgba(21, 34, 56, 0.04);
    }

    .map-shell {
        background: #fff;
        border: 1px solid #ddd4c4;
        border-radius: 8px;
        padding: 0.4rem;
        box-shadow: 0 8px 24px rgba(21, 34, 56, 0.08);
        overflow: hidden;
    }

    .legend-panel {
        background: #fff;
        border: 1px solid #ddd4c4;
        border-radius: 8px;
        padding: 0.9rem 1rem;
        height: 100%;
    }

    .legend-panel h4 {
        font-family: "Cormorant Garamond", Georgia, serif;
        margin: 0 0 0.65rem 0;
        font-size: 1.15rem;
        color: #152238;
    }

    .legend-item {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        margin: 0.38rem 0;
        font-size: 0.9rem;
    }

    .legend-swatch {
        width: 16px;
        height: 16px;
        border: 1px solid rgba(0,0,0,0.18);
        flex-shrink: 0;
    }

    .query-card {
        background: #fff;
        border: 1px solid #ddd4c4;
        border-radius: 8px;
        padding: 0.95rem 1rem;
        margin-top: 0.75rem;
    }

    .query-card h4 {
        font-family: "Cormorant Garamond", Georgia, serif;
        margin: 0 0 0.7rem 0;
        color: #152238;
        font-size: 1.2rem;
    }

    .risk-badge {
        display: inline-block;
        padding: 0.22rem 0.7rem;
        border-radius: 2px;
        font-weight: 700;
        font-size: 0.82rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: #fff;
    }

    .risk-clean { background: #2e7d32; }
    .risk-slightly_contaminated { background: #f9a825; color: #1f2933; }
    .risk-moderate { background: #ef6c00; }
    .risk-heavy { background: #c62828; }

    .notice {
        background: #fff8e5;
        border-left: 4px solid #c4a35a;
        padding: 0.7rem 0.85rem;
        font-size: 0.88rem;
        margin: 0.4rem 0 0.8rem 0;
    }

    .page-copy {
        background: #fff;
        border: 1px solid #ddd4c4;
        border-radius: 8px;
        padding: 0.8rem 1rem;
    }

    .page-copy h1, .page-copy h2, .page-copy h3 {
        font-family: "Cormorant Garamond", Georgia, serif;
        color: #152238;
    }

    div[data-testid="stMetric"] {
        background: #f8f5ef;
        border: 1px solid #e6dece;
        padding: 0.65rem 0.7rem;
        border-radius: 6px;
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
