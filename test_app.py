import streamlit as st
import folium
from streamlit_folium import st_folium

st.title("Test Map")

# Create a simple map
m = folium.Map(location=[0.25, 34.75], zoom_start=10)

# Add a marker
folium.Marker([0.25, 34.75], popup="Test Marker").add_to(m)

# Display map
st_folium(m, width="100%", height=600)

st.success("Map should be displayed above!")
