import streamlit as st
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Kakamega Map", layout="wide")

st.title("Kakamega Heavy Metal Risk Assessment")
st.markdown("Interactive map for contamination risk assessment")

# Create a simple map centered on Kakamega
m = folium.Map(location=[0.25, 34.75], zoom_start=10, control_scale=True)

# Add satellite imagery
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri',
    name='Satellite',
    overlay=False,
    control=True
).add_to(m)

# Add OpenStreetMap
folium.TileLayer(
    tiles='OpenStreetMap',
    name='OpenStreetMap',
    overlay=False,
    control=True
).add_to(m)

# Add layer control
folium.LayerControl().add_to(m)

# Display map
st_folium(m, width="100%", height=600)

st.success("Map loaded successfully!")
