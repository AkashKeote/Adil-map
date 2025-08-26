"""
Simple Map Route Server for Vercel Deployment
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import tempfile
import json

app = Flask(__name__)
CORS(app)

# Sample route data
sample_routes = {
    "andheri": {
        "matched": "Andheri East",
        "score": 95,
        "routes": [
            {
                "dest_region": "Bandra West",
                "distance_km": 5.2,
                "eta_min": 15.6,
                "coordinates": [[19.1197, 72.8697], [19.0544, 72.8267]]
            },
            {
                "dest_region": "Colaba",
                "distance_km": 8.7,
                "eta_min": 26.1,
                "coordinates": [[19.1197, 72.8697], [18.9067, 72.8147]]
            }
        ]
    },
    "bandra": {
        "matched": "Bandra West", 
        "score": 98,
        "routes": [
            {
                "dest_region": "Fort",
                "distance_km": 6.3,
                "eta_min": 18.9,
                "coordinates": [[19.0544, 72.8267], [18.9322, 72.8264]]
            }
        ]
    }
}

@app.route("/")
def home():
    return jsonify({
        "message": "🗺️ Map Route Server",
        "version": "vercel-v1.0",
        "endpoints": {
            "GET /map": "Get evacuation map (query param: region)",
            "POST /routes": "Get evacuation routes"
        }
    })

@app.route("/map")
def map_page():
    region = request.args.get("region", "").lower()
    if not region:
        return "❌ Region not provided", 400

    # Generate simple HTML map
    map_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Evacuation Map - {region.title()}</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ margin: 0; padding: 20px; font-family: Arial, sans-serif; }}
            .map-container {{ background: #f0f0f0; padding: 20px; border-radius: 10px; }}
            .info {{ background: white; padding: 15px; margin: 10px 0; border-radius: 5px; }}
        </style>
    </head>
    <body>
        <h1>🗺️ Evacuation Map for {region.title()}</h1>
        <div class="map-container">
            <div class="info">
                <h3>📍 Current Location: {region.title()}</h3>
                <p>This is a simplified evacuation map. In a real deployment, this would show:</p>
                <ul>
                    <li>Interactive map with roads and routes</li>
                    <li>Safe evacuation paths highlighted</li>
                    <li>Emergency shelters and hospitals</li>
                    <li>Real-time traffic conditions</li>
                </ul>
            </div>
            <div class="info">
                <h3>🚨 Evacuation Instructions</h3>
                <p>1. Move to higher ground immediately</p>
                <p>2. Follow marked evacuation routes</p>
                <p>3. Avoid flooded areas and underpasses</p>
                <p>4. Contact emergency services if needed: 108</p>
            </div>
        </div>
        <script>
            console.log('Map loaded for region: {region}');
        </script>
    </body>
    </html>
    """
    
    return map_html

@app.route("/routes", methods=["POST"])
def get_routes():
    try:
        data = request.get_json()
        region = data.get("region", "").lower()
        
        if not region:
            return jsonify({"error": "Region is required"}), 400
            
        # Find matching routes
        route_data = None
        for key, value in sample_routes.items():
            if key in region or region in key:
                route_data = value
                break
                
        if not route_data:
            return jsonify({
                "error": f"No routes found for region: {region}",
                "available_regions": list(sample_routes.keys())
            }), 404
            
        return jsonify({
            "success": True,
            "matched_region": route_data["matched"],
            "score": route_data["score"],
            "routes": route_data["routes"],
            "message": f"Found {len(route_data['routes'])} evacuation routes"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# For Vercel deployment
def handler(request):
    return app(request.environ, lambda *args: None)

if __name__ == "__main__":
    app.run(debug=True)
