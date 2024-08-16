from flask import Flask, render_template, request, jsonify
import requests
import geopandas as gpd
from shapely.geometry import Point

def geocode_input(input_string):
    # Check if input is coordinates (e.g., "40.7128,-74.0060")
    if ',' in input_string:
        try:
            lat, lon = map(float, input_string.split(','))
            return Point(lon, lat)
        except ValueError:
            return None
    else:
        # Input is assumed to be an address
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
borough_shapefile = gpd.read_file("C:/Users/sk9655/Downloads/Untitled Folder/CDW calculator/Borough_Boundaries.geojson")

borough_waste_composition = {
    "Manhattan": {"asphalt": 0.1, "concrete": 0.15, "gravel": 0.25, "dirt": 0.5},
    "Brooklyn": {"asphalt": 0.12, "concrete": 0.18, "gravel": 0.20, "dirt": 0.5},
    "Queens": {"asphalt": 0.08, "concrete": 0.12, "gravel": 0.30, "dirt": 0.5},
    "Bronx": {"asphalt": 0.11, "concrete": 0.15, "gravel": 0.24, "dirt": 0.5},
    "Staten Island": {"asphalt": 0.13, "concrete": 0.17, "gravel": 0.20, "dirt": 0.5}
}
# Still to be tested and included with real Values 
material_composition = {
    'asphalt': 0.1,
    'concrete': 0.15,
    'gravel': 0.25,
    'dirt': 0.5
}

emission_factors = {
    'EF_prod_asphalt': 85,    # kg CO2e/m³
    'EF_prod_concrete': 120,  # kg CO2e/m³
    'EF_prod_gravel': 20,     # kg CO2e/m³
    'EF_prod_dirt': 10,       # kg CO2e/m³
    'EF_excavator': 50,       # kg CO2e/hour
    'EF_bulldozer': 70,       # kg CO2e/hour
    'EF_transport': 0.1,      # kg CO2e/ton-km
    'EF_landfill': 5,         # kg CO2e/ton
    'EF_recycling': 3         # kg CO2e/ton
}

equipment_usage_rates = {
    'excavator': 0.1,   # hours/m³
    'bulldozer': 0.05   # hours/m³
}

distances = {
    'to_recycling_center': 20,   # km
    'from_recycling_center_to_landfill': 30,  # km
    'to_site': 50  # km
}

material_densities = {
    'asphalt': 2.4,  # tons/m³
    'concrete': 2.3, # tons/m³
    'gravel': 1.6,   # tons/m³
    'dirt': 1.5      # tons/m³
}

# Calculate excavation volume
V = float(data.get('length', 0)) * float(data.get('width', 0)) * float(data.get('depth', 0))
# Calculate emissions for extraction and production of materials
def calculate_emissions_prod(material, volume, emission_factor):
    return volume * emission_factor

emissions_prod = {}
for material, proportion in material_composition.items():
    volume = V * proportion
    emissions_prod[material] = calculate_emissions_prod(material, volume, emission_factors[f'EF_prod_{material}'])

# Calculate emissions for transporting materials to site
def calculate_emissions_transport(weight, distance, emission_factor):
    return weight * distance * emission_factor

emissions_transport_to_site = {}
total_weight = 0
for material, proportion in material_composition.items():
    volume = V * proportion
    weight = volume * material_densities[material]
    total_weight += weight
    emissions_transport_to_site[material] = calculate_emissions_transport(weight, distances['to_site'], emission_factors['EF_transport'])

# Calculate emissions for excavation equipment
def calculate_emissions_equipment(volume, usage_rate, emission_factor):
    return volume * usage_rate * emission_factor

total_excavator_hours = V * equipment_usage_rates['excavator']
total_bulldozer_hours = V * equipment_usage_rates['bulldozer']

emissions_excavator = total_excavator_hours * emission_factors['EF_excavator']
emissions_bulldozer = total_bulldozer_hours * emission_factors['EF_bulldozer']

# Calculate emissions for transporting excavated material
emissions_transport_to_recycling = calculate_emissions_transport(total_weight, distances['to_recycling_center'], emission_factors['EF_transport'])
emissions_transport_to_landfill = calculate_emissions_transport(total_weight, distances['from_recycling_center_to_landfill'], emission_factors['EF_transport'])

# Calculate emissions from waste management
emissions_landfill = total_weight * emission_factors['EF_landfill']
emissions_recycling = total_weight * emission_factors['EF_recycling']

# Sum total emissions
total_emissions = (
    sum(emissions_prod.values()) +
    sum(emissions_transport_to_site.values()) +
    emissions_excavator +
    emissions_bulldozer +
    emissions_transport_to_recycling +
    emissions_transport_to_landfill +
    emissions_landfill +
    emissions_recycling
)

# Output the results
print(f"Total Emissions: {total_emissions} kg CO2e")
print(f"Emissions from Production of Materials: {sum(emissions_prod.values())} kg CO2e")
print(f"Emissions from Transporting Materials to Site: {sum(emissions_transport_to_site.values())} kg CO2e")
print(f"Emissions from Excavator: {emissions_excavator} kg CO2e")
print(f"Emissions from Bulldozer: {emissions_bulldozer} kg CO2e")
print(f"Emissions from Transporting to Recycling: {emissions_transport_to_recycling} kg CO2e")
print(f"Emissions from Transporting to Landfill: {emissions_transport_to_landfill} kg CO2e")
print(f"Emissions from Landfill: {emissions_landfill} kg CO2e")
print(f"Emissions from Recycling: {emissions_recycling} kg CO2e")

# Till here 

def determine_borough(point):
    if point:
        # Check each borough polygon to see if it contains the point
        for index, row in borough_shapefile.iterrows():
            if row['geometry'].contains(point):
                return row['boro_name']
    return "Unknown"

app = Flask(__name__)
@app.route('/')
def index():
    return render_template('index2.html')

@app.route('/calculate', methods=['POST'])
def calculate_waste():
    try:
        data = request.get_json()
        location = data.get('location')
        length = float(data.get('length', 0))
        width = float(data.get('width', 0))
        depth = float(data.get('depth', 0))

        point = Point(location['lng'], location['lat'])
        borough = determine_borough(point)
        composition = borough_waste_composition.get(borough)

        waste_quantities = {material: length * width * depth * percentage for material, percentage in composition.items()}

        return jsonify(waste_quantities)
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"error": "Error processing request, please check input values."}), 500


if __name__ == '__main__':
    app.run(debug=True)