"""Download ERA5 wind data for Shaanxi province."""
import cdsapi
from datetime import datetime

# Shaanxi bounding box: [North, West, South, East]
SHAANXI_BBOX = [40, 105, 31, 112]

client = cdsapi.Client()

request = {
    'product_type': ['reanalysis'],
    'variable': ['10m_u_component_of_wind', '10m_v_component_of_wind'],
    'year': ['2024'],
    'month': [f'{m:02d}' for m in range(1, 13)],
    'day': [f'{d:02d}' for d in range(1, 32)],
    'time': [f'{h:02d}:00' for h in range(24)],
    'area': SHAANXI_BBOX,
    'data_format': 'netcdf',
    'download_format': 'unarchived',
}

print("Downloading ERA5 wind data for Shaanxi (2024)...")
client.retrieve('reanalysis-era5-single-levels', request).download('era5_wind_shaanxi_2024.nc')
print("Download complete: era5_wind_shaanxi_2024.nc")
