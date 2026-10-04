# Kakamega Heavy Metal Risk Assessment Portal

An interactive WebGIS application built with Streamlit and Folium for predicting and visualizing heavy metal contamination around artisanal gold mines in Kakamega County, Kenya.

## Features

- **Interactive Map**: Explore contamination risk levels across Kakamega County with satellite imagery and multiple basemap options
- **Click-to-Query**: Click anywhere on the map to see exact contamination concentrations and risk levels
- **Raster Overlay**: Visualize predicted contamination with adjustable opacity
- **Multiple Pages**: 
  - Interactive Map
  - Check My Location (GPS-based)
  - Data Explorer
  - Model Results
  - Methodology
  - About the Project
  - Key Statistics
  - Disclaimer
- **Risk Classification**: 4-tier color-coded risk assessment (Clean, Slightly Contaminated, Moderate, Heavy Contamination)

## Project Structure

```
kakamega-risk-portal/
├── .streamlit/
│   └── config.toml              # Streamlit configuration
├── data/
│   ├── Raster/
│   │   └── Training_raster.tif  # GeoTIFF raster with contamination predictions
│   └── vector/                  # Optional vector data (boundaries, points)
├── assets/
│   └── logo.png                 # Dedan Kimathi University logo
├── utils/
│   ├── raster_processor.py      # GeoTIFF processing, CRS handling, sampling
│   └── styles.py                # Custom CSS styling
├── app.py                       # Main Streamlit application
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Installation

### Local Development

1. **Clone or download this repository**

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   
   # On Windows:
   venv\Scripts\activate
   
   # On Mac/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Prepare your data**:
   - Place your GeoTIFF raster file at `data/Raster/Training_raster.tif`
   - The raster should be in a projected CRS (e.g., UTM) or WGS84
   - The app will automatically reproject to WGS84 for display
   - If no raster is found, a fallback test raster will be created automatically

5. **Add the university logo** (optional):
   - Place the Dedan Kimathi University logo at `assets/logo.png`
   - Recommended size: 150x150 pixels
   - If no logo is found, a text placeholder will be displayed

6. **Run the application**:
   ```bash
   streamlit run app.py
   ```

7. **Open your browser**:
   The app will open at `http://localhost:8501`

## Deployment to Streamlit Cloud

### Option 1: Using GitHub (Recommended)

1. **Push your code to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/yourusername/kakamega-risk-portal.git
   git push -u origin main
   ```

2. **Deploy to Streamlit Cloud**:
   - Go to [share.streamlit.io](https://share.streamlit.io)
   - Click "New app"
   - Connect your GitHub account
   - Select your repository
   - Set the main file path to `app.py`
   - Click "Deploy"

### Option 2: Using the Streamlit CLI

1. **Install the Streamlit CLI**:
   ```bash
   pip install streamlit
   ```

2. **Login to Streamlit**:
   ```bash
   streamlit login
   ```

3. **Deploy**:
   ```bash
   streamlit deploy
   ```

## Data Requirements

### Raster Data Format

The application expects a GeoTIFF raster file with the following characteristics:

- **Format**: GeoTIFF (.tif)
- **Bands**: Single band with contamination concentration values
- **Values**: Numerical values representing heavy metal concentration (mg/kg or ppm)
- **CRS**: Any projected CRS (e.g., UTM Zone 36N / EPSG:32636) or WGS84
- **NoData**: Properly defined NoData values for transparency

### Risk Classification Thresholds

The app uses the following thresholds (adjustable in `utils/raster_processor.py`):

- **Clean**: ≤ 0.5 mg/kg (Green)
- **Slightly Contaminated**: 0.5-1.0 mg/kg (Yellow)
- **Moderate**: 1.0-2.0 mg/kg (Orange)
- **Heavy Contamination**: > 2.0 mg/kg (Red)

To customize thresholds, edit the `RISK_THRESHOLDS` dictionary in `utils/raster_processor.py`.

## Configuration

### Streamlit Configuration

Edit `.streamlit/config.toml` to customize:

- Theme colors
- Font settings
- Upload size limits
- Server settings

### CRS Handling

The app automatically handles CRS reprojection:
- Input raster can be in any CRS
- Automatically reprojects to WGS84 (EPSG:4326) for Folium display
- Click coordinates are transformed back to raster CRS for accurate sampling

## Dependencies

- `streamlit>=1.30.0` - Web framework
- `folium>=0.15.0` - Map visualization
- `streamlit-folium>=0.18.0` - Streamlit-Folium integration
- `rasterio>=1.3.8` - GeoTIFF processing
- `numpy>=1.24.0` - Numerical operations
- `matplotlib>=3.8.0` - Color handling
- `branca>=0.7.0` - Colormap utilities
- `pyproj>=3.6.0` - CRS transformations

All dependencies use pre-compiled wheels suitable for Streamlit Cloud.

## Troubleshooting

### Raster Not Loading

- **Error**: "Failed to load raster"
- **Solution**: Check that the raster file exists at `data/Raster/Training_raster.tif`
- **Solution**: Ensure the raster has a valid CRS defined
- **Solution**: Check file permissions

### CRS Reprojection Issues

- **Error**: "Raster has no CRS defined"
- **Solution**: Define the CRS in your GeoTIFF using GIS software (QGIS, ArcGIS)
- **Solution**: Use `gdal_edit.py` to assign CRS: `gdal_edit.py -a_srs EPSG:32636 data/Raster/Training_raster.tif`

### Memory Issues

- **Error**: Application crashes with large rasters
- **Solution**: Downsample your raster to a reasonable resolution (e.g., 1000x1000 pixels max)
- **Solution**: Use cloud-optimized GeoTIFF format

### Streamlit Cloud Deployment Issues

- **Error**: Build fails during deployment
- **Solution**: Ensure all dependencies are in `requirements.txt`
- **Solution**: Check that paths are relative (not absolute)
- **Solution**: Verify the raster file is included in the repository (or use external storage)

## Customization

### Adding New Pages

Add a new page function in `app.py`:

```python
def page_new_page():
    """Your new page content."""
    st.markdown("## New Page")
    # Add your content here
```

Then add it to the navigation radio in the `main()` function.

### Changing Color Scheme

Edit the `RISK_COLORS` dictionary in `utils/raster_processor.py` and update the CSS in `utils/styles.py`.

### Adding New Basemaps

Add new tile layers in the `create_base_map()` function in `app.py`:

```python
folium.TileLayer(
    tiles='your_tile_url',
    attr='Your attribution',
    name='Your Layer Name',
    overlay=False,
    control=True
).add_to(m)
```

## Research Team

- **Researcher**: Susan Wambui Mungai
- **Course**: BSc Geology
- **Supervisor**: Dr. Patrick Gevera
- **Institution**: Dedan Kimathi University of Technology

## License

This project is for academic research purposes. Please contact the research team for permission to use or modify.

## Acknowledgments

- Built with [Streamlit](https://streamlit.io)
- Map visualization powered by [Folium](https://python-visualization.github.io/folium/)
- Raster processing with [Rasterio](https://rasterio.readthedocs.io/)
- Basemap data from [Esri](https://www.esri.com) and [OpenStreetMap](https://www.openstreetmap.org)

## Contact

For questions or feedback about this application, please contact the research team at Dedan Kimathi University of Technology.
