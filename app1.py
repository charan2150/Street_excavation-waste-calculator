import os
from flask import Flask, render_template, request, jsonify
import requests
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, LineString
import logging
from flask_cors import CORS
app = Flask(__name__, static_folder='static')
CORS(app)
static_path = os.path.join(app.root_path, 'static')
def geocode_input(input_string):
    if ',' in input_string:
        try:
            lat, lon = map(float, input_string.split(','))
            return Point(lon, lat)
        except ValueError:
            return None
    else:
        url = "https://trueway-geocoding.p.rapidapi.com/Geocode"
        querystring = {"address": input_string, "language": "en"}
        headers = {
            "X-RapidAPI-Key": "5930c633bcmsh554e2b895fdf6a6p12fafajsne72a0a2dfe0e",
            "X-RapidAPI-Host": "trueway-geocoding.p.rapidapi.com"
        }
        response = requests.get(url, headers=headers, params=querystring)
        data = response.json()

        if data['results']:
            location = data['results'][0]['location']
            return Point(location['lng'], location['lat'])

    return None

def calculate_dynamic_waste_composition(depth):
    composition = {}
    remaining_depth = depth

    for material, thickness in layer_thicknesses.items():
        if remaining_depth <= 0:
            break
        if remaining_depth >= thickness:
            composition[material] = thickness / depth  # full layer
            remaining_depth -= thickness
        else:
            composition[material] = remaining_depth / depth  # partial layer
            remaining_depth = 0

    # Adjust remaining depth to dirt if it's not fully accounted for
    if remaining_depth > 0:
        composition["dirt"] = remaining_depth / depth

    return composition

def calculate_waste_composition(borough, depth):
    if depth <= 0:
        raise ValueError("Depth must be greater than 0.")

    if borough in borough_waste_composition:
        return calculate_dynamic_waste_composition(depth)
    else:
        raise ValueError("Borough not found.")


def get_route(origin, destination):
    url = f"https://router.project-osrm.org/route/v1/driving/{origin.x},{origin.y};{destination.x},{destination.y}?geometries=geojson"
    response = requests.get(url)
    data = response.json()
    if data['code'] == 'Ok':
        return data['routes'][0]['geometry']['coordinates']
    return []

borough_shapefile = gpd.read_file(os.path.join(static_path, 'Borough_Boundaries.geojson'))
census_blocks = gpd.read_file(os.path.join(static_path, 'data/NYC_Census_2020.shp')).to_crs(epsg=4326)
cb_to_ts = gpd.read_file(os.path.join(static_path, 'data/census_blocks_to_TS_filtered.shp')).to_crs(epsg=4326)
ts_to_landfill = pd.read_csv(os.path.join(static_path, 'data/Transfer_to_Landfill_filtered.csv'))
logging.debug(f"Static path: {static_path}")
logging.debug(f"Borough shapefile path: {os.path.join(static_path, 'Borough_Boundaries.geojson')}")
logging.debug(f"Census blocks shapefile path: {os.path.join(static_path, 'data/NYC_Census_2020.shp')}")

borough_waste_composition = {
    "Manhattan": {"asphalt": 0.1, "concrete": 0.15, "gravel": 0.25, "dirt": 0.5},
    "Brooklyn": {"asphalt": 0.12, "concrete": 0.18, "gravel": 0.20, "dirt": 0.5},
    "Queens": {"asphalt": 0.08, "concrete": 0.12, "gravel": 0.30, "dirt": 0.5},
    "Bronx": {"asphalt": 0.11, "concrete": 0.15, "gravel": 0.24, "dirt": 0.5},
    "Staten Island": {"asphalt": 0.13, "concrete": 0.17, "gravel": 0.20, "dirt": 0.5}
}

layer_thicknesses = {
    "asphalt": 0.1524,  # 6 inches in meters
    "concrete": 0.1524,  # 6 inches in meters
    # Add more layers if needed, with their respective thicknesses
}

emission_factors = {
    'EF_prod_asphalt': 85,    # kg CO2e/m³
    'EF_prod_concrete': 120,  # kg CO2e/m³
    'EF_prod_gravel': 20,     # kg CO2e/m³
    'EF_prod_dirt': 10,       # kg CO2e/m³
    'EF_excavator': 25,       # kg CO2e/hour
    'EF_bulldozer': 70,       # kg CO2e/hour
    'EF_transport': 0.15,      # kg CO2e/ton-mile
    'EF_landfill': 5,         # kg CO2e/ton
    'EF_recycling': 3         # kg CO2e/ton
}

equipment_usage_rates = {
    'excavator': 0.1,   # hours/m³
    'bulldozer': 0.05   # hours/m³
}

material_densities = {
    'asphalt': 2.4,  # tons/m³
    'concrete': 2.3, # tons/m³
    'gravel': 1.6,   # tons/m³
    'dirt': 1.5      # tons/m³
}

@app.route('/')
def index():
    return render_template('index2.html')

@app.route('/calculate', methods=['POST'])
def calculate_waste():
    try:
        data = request.get_json()
        logging.debug(f"Received data: {data}")

        location = data.get('location')
        length = float(data.get('length', 0))
        width = float(data.get('width', 0))
        depth = float(data.get('depth', 0))

        logging.debug(f"Parsed input - Location: {location}, Length: {length}, Width: {width}, Depth: {depth}")

        point = Point(location['lng'], location['lat'])
        logging.debug(f"Searching for census block containing point: {point}")
        
        # Find the census block
        census_block = census_blocks[census_blocks.contains(point)]
        if census_block.empty:
            raise ValueError("No census block found for the given location.")
        
        census_block_geoid = census_block.iloc[0]['GEOID']
        logging.debug(f"Found census block with GEOID: {census_block_geoid}")

        # Find the nearest transfer station
        ts_row = cb_to_ts[cb_to_ts['origin_id'] == census_block_geoid].iloc[0]
        logging.debug(f"Transfer Station Row: {ts_row}")

        ts_id = ts_row['destinatio']
        ts_cost = ts_row['total_cost'] / 1609.34  # Convert meters to miles
        transfer_station_point = ts_row['geometry'].coords[-1]  # Get the last coordinate of the LineString
        transfer_station_point = Point(transfer_station_point)
        logging.debug(f"Transfer Station ID: {ts_id}")

        # Find the nearest landfill
        landfill_row = ts_to_landfill[ts_to_landfill['origin_id'] == ts_id].nsmallest(1, 'total_cost').iloc[0]
        landfill_cost = landfill_row['total_cost'] / 1609.34  # Convert meters to miles
        logging.debug(f"Landfill Row: {landfill_row}")

        # Calculate emissions
        V = length * width * depth * 0.8  # 0.8 is a fill factor
        emissions_prod = {}
        total_weight = 0

        borough = determine_borough(point)
        composition = calculate_waste_composition( borough,depth)

        for material, proportion in composition.items():
            volume = V * proportion
            emissions_prod[material] = volume * emission_factors[f'EF_prod_{material}']
            weight = volume * material_densities[material]
            total_weight += weight

        emissions_transport_to_site = total_weight * ts_cost * emission_factors['EF_transport']* 0
        total_excavator_hours = V * equipment_usage_rates['excavator']
        total_bulldozer_hours = V * equipment_usage_rates['bulldozer']

        emissions_excavator = total_excavator_hours * emission_factors['EF_excavator']
        emissions_bulldozer = total_bulldozer_hours * emission_factors['EF_bulldozer']

        emissions_transport_to_recycling = total_weight * ts_cost * emission_factors['EF_transport']
        emissions_transport_to_landfill = total_weight * 0.1 * landfill_cost * emission_factors['EF_transport']

        emissions_landfill = total_weight * 0.1 * emission_factors['EF_landfill']
        emissions_recycling = total_weight * emission_factors['EF_recycling']

        total_emissions = (
            sum(emissions_prod.values()) +
            emissions_transport_to_site +
            emissions_excavator +
            emissions_bulldozer +
            emissions_transport_to_recycling +
            emissions_transport_to_landfill +
            emissions_landfill +
            emissions_recycling
        )

        # Get route coordinates
        route_coords = get_route(point, transfer_station_point)
        
        response = {
            "Total emissions": total_emissions,
            "Emissions from production": sum(emissions_prod.values()),
            "Emissions from excavator": emissions_excavator,
            "Emissions from bulldozer": emissions_bulldozer,
            "Emissions from transporting to recycling": emissions_transport_to_recycling,
            "Emissions from transporting to landfill": emissions_transport_to_landfill,
            "Emissions from landfill": emissions_landfill,
            "Emissions from recycling": emissions_recycling,
            "route_coords": route_coords,
            "ts_distance": ts_cost,
            "transfer_station": {
                "name": "Closest CDW Transfer Station",
                "location": {
                    "lat": transfer_station_point.y,
                    "lng": transfer_station_point.x
                }
            }
        }

        return jsonify(response)
    except Exception as e:
        logging.error(f"Error: {str(e)}", exc_info=True)
        return jsonify({"error": "Error processing request, please check input values."}), 500

def determine_borough(point):
    if point:
        for index, row in borough_shapefile.iterrows():
            if row['geometry'].contains(point):
                return row['boro_name']
    return "Unknown"

if __name__ == '__main__':
    app.run(debug=True)
