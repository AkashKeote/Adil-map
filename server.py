#!/usr/bin/env python3
"""
Backend API Server for Flood Prediction and Evacuation Routes
Integrated with llload.py for dynamic map generation
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
import sys

# Add current directory to Python path to import llload.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Try to import llload.py functionality (can be disabled via env to keep Vercel light)
ENABLE_LLLOAD = os.getenv("ENABLE_LLLOAD", "0").lower() in ("1", "true", "yes")
LLLOAD_AVAILABLE = False
if ENABLE_LLLOAD:
    try:
        from llload import (
            get_k_nearest_low_risk_routes,
            build_and_save_map,
            G, flood_df, ROUTE_COUNT
        )
        LLLOAD_AVAILABLE = True
        print("✅ llload.py successfully imported")
    except ImportError as e:
        print(f"⚠️ Warning: Could not import llload.py - {e}")
        print("📝 Using fallback static data instead")
        LLLOAD_AVAILABLE = False
else:
    print("ℹ️ ENABLE_LLLOAD is disabled. Running with static fallback data only.")

app = Flask(__name__)
CORS(app)

# Mumbai regions data (from your CSV)
MUMBAI_REGIONS = [
    "Andheri East", "Andheri West", "Bandra East", "Bandra West", 
    "Colaba", "Fort", "Dadar", "Worli", "Powai", "Borivali",
    "Malad", "Goregaon", "Versova", "Juhu", "Santacruz", "Khar",
    "Mahim", "Sion", "Kurla", "Ghatkopar", "Thane", "Mulund"
]

# Sample flood risk data
FLOOD_RISK_DATA = {
    "Andheri East": "high", "Andheri West": "moderate", "Bandra East": "low", 
    "Bandra West": "low", "Colaba": "low", "Fort": "low", "Dadar": "moderate",
    "Worli": "low", "Powai": "high", "Borivali": "low", "Malad": "moderate",
    "Goregaon": "moderate", "Versova": "moderate", "Juhu": "moderate", 
    "Santacruz": "moderate", "Khar": "low", "Mahim": "moderate", 
    "Sion": "high", "Kurla": "high", "Ghatkopar": "moderate", 
    "Thane": "moderate", "Mulund": "low"
}

# Sample evacuation routes data
EVACUATION_ROUTES = {
    "Andheri East": [
        {"destination": "Borivali", "distance_km": 12.3, "eta": "29.5 min", "risk_level": "low"},
        {"destination": "Colaba", "distance_km": 18.7, "eta": "44.9 min", "risk_level": "low"},
        {"destination": "Fort", "distance_km": 16.2, "eta": "38.9 min", "risk_level": "low"}
    ],
    "Thane": [
        {"destination": "Mulund", "distance_km": 8.5, "eta": "20.4 min", "risk_level": "low"},
        {"destination": "Borivali", "distance_km": 15.2, "eta": "36.5 min", "risk_level": "low"},
        {"destination": "Khar", "distance_km": 22.1, "eta": "53.0 min", "risk_level": "low"}
    ]
}

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route("/")
def home():
    """API Information"""
    return jsonify({
        "message": "🌊 Mumbai Flood Prediction & Evacuation Routes API",
        "version": "2.0.0 - Backend Only",
        "endpoints": {
            "health": "/health",
            "regions": "/regions", 
            "predict_flood": "/predict_flood (POST)",
            "routes": "/routes (POST)",
            "map": "/map?region=<region_name>"
        },
        "status": "✅ Backend Only - No Frontend Files",
        "deployment": "Vercel Serverless"
    })

@app.route("/health")
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "message": "Backend API is running perfectly!",
        "service": "Mumbai Evacuation Routes API",
        "regions_count": len(MUMBAI_REGIONS),
        "llload_status": "connected" if LLLOAD_AVAILABLE else "not_available",
        "data_source": "Dynamic (llload.py)" if LLLOAD_AVAILABLE else "Static fallback"
    })

@app.route("/test_llload")
def test_llload():
    """Test llload.py connection and functionality"""
    result = {
        "llload_available": LLLOAD_AVAILABLE,
        "timestamp": json.dumps(None),  # Will be replaced with actual timestamp
    }
    
    if LLLOAD_AVAILABLE:
        try:
            # Test basic functionality
            test_region = "andheri"
            matched_region, match_score, routes_data = get_k_nearest_low_risk_routes(
                test_region, G, flood_df, k=3
            )
            
            result.update({
                "test_status": "success",
                "test_region": test_region,
                "matched_region": matched_region,
                "match_score": match_score,
                "routes_found": len(routes_data) if routes_data else 0,
                "graph_nodes": len(G.nodes) if G else 0,
                "graph_edges": len(G.edges) if G else 0,
                "flood_data_regions": len(flood_df) if flood_df is not None else 0,
                "sample_routes": routes_data[:2] if routes_data else [],
                "message": "✅ llload.py is working correctly!"
            })
        except Exception as e:
            result.update({
                "test_status": "error",
                "error": str(e),
                "message": "❌ llload.py test failed"
            })
    else:
        result.update({
            "test_status": "not_available",
            "message": "⚠️ llload.py not available - using static data"
        })
    
    return jsonify(result)

@app.route("/regions")
def regions():
    """Get all available regions"""
    return jsonify({
        "regions": MUMBAI_REGIONS,
        "count": len(MUMBAI_REGIONS),
        "message": f"Found {len(MUMBAI_REGIONS)} Mumbai regions"
    })

@app.route("/predict_flood", methods=['POST'])
def predict_flood():
    """Predict flood risk for a ward"""
    try:
        data = request.get_json()
        ward_name = data.get('ward_name', '')
        
        if not ward_name:
            return jsonify({"error": "ward_name is required"}), 400
        
        # Find matching region (case insensitive)
        matched_region = None
        for region in MUMBAI_REGIONS:
            if ward_name.lower() in region.lower() or region.lower() in ward_name.lower():
                matched_region = region
                break
        
        if not matched_region:
            return jsonify({
                "error": f"Ward '{ward_name}' not found",
                "ward": ward_name,
                "available_regions": MUMBAI_REGIONS[:10]
            }), 404
        
        risk_level = FLOOD_RISK_DATA.get(matched_region, "moderate")
        
        return jsonify({
            "ward": matched_region,
            "risk_level": risk_level,
            "confidence": 0.87,
            "message": f"Flood risk level for {matched_region} is {risk_level}"
        })
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "ward": ward_name if 'ward_name' in locals() else "unknown"
        }), 500

@app.route("/routes", methods=['POST'])
def get_routes():
    """Get evacuation routes for a region"""
    try:
        data = request.get_json()
        region = data.get('region', '')
        route_count = data.get('route_count', 3)
        
        if not region:
            return jsonify({"error": "region is required"}), 400
        
        # Try to use llload.py first for dynamic routes
        if LLLOAD_AVAILABLE:
            try:
                matched_region, match_score, routes_data = get_k_nearest_low_risk_routes(
                    region, G, flood_df, k=route_count
                )
                
                if matched_region and routes_data:
                    # Convert llload routes format to API format
                    routes = []
                    for route in routes_data:
                        routes.append({
                            "destination": route['dest_region'],
                            "distance_km": route['distance_km'],
                            "eta": f"{route['eta_min']:.1f} min",
                            "risk_level": "low",  # All routes from llload are to low-risk areas
                        })
                    
                    return jsonify({
                        "success": True,
                        "matched_region": matched_region,
                        "match_score": match_score,
                        "routes": routes,
                        "route_count": len(routes),
                        "message": f"Found {len(routes)} evacuation routes from {matched_region} using dynamic routing",
                        "data_source": "llload.py - Dynamic Routes"
                    })
            except Exception as e:
                print(f"⚠️ llload.py failed, falling back to static data: {e}")
        
        # Fallback to static data
        matched_region = None
        for r in MUMBAI_REGIONS:
            if region.lower() in r.lower() or r.lower() in region.lower():
                matched_region = r
                break
        
        if not matched_region:
            return jsonify({
                "error": f"Region '{region}' not found",
                "matched_region": None,
                "available_regions": MUMBAI_REGIONS[:10]
            }), 404
        
        # Get static evacuation routes
        routes = EVACUATION_ROUTES.get(matched_region, [
            {"destination": "Safe Zone 1", "distance_km": 10.5, "eta": "25.2 min", "risk_level": "low"},
            {"destination": "Safe Zone 2", "distance_km": 15.2, "eta": "36.5 min", "risk_level": "low"},
            {"destination": "Safe Zone 3", "distance_km": 8.7, "eta": "20.9 min", "risk_level": "low"}
        ])
        
        routes = routes[:route_count]
        
        return jsonify({
            "success": True,
            "matched_region": matched_region,
            "match_score": 85,
            "routes": routes,
            "route_count": len(routes),
            "message": f"Found {len(routes)} evacuation routes from {matched_region} using static data",
            "data_source": "Static Data - Fallback"
        })
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "matched_region": region if 'region' in locals() else "unknown"
        }), 500

@app.route("/map")
def map_page():
    """Generate evacuation map using llload.py or fallback HTML"""
    try:
        region = request.args.get("region", "")
        if not region:
            return jsonify({"error": "Region parameter is required"}), 400

        # Try to use llload.py for dynamic interactive map generation
        if LLLOAD_AVAILABLE:
            try:
                matched_region, match_score, routes_data = get_k_nearest_low_risk_routes(
                    region, G, flood_df, k=ROUTE_COUNT
                )
                
                if matched_region and routes_data:
                    # Generate dynamic HTML map using llload.py
                    map_file = f"temp_evacuation_map_{matched_region.replace(' ', '_')}.html"
                    build_and_save_map(matched_region, routes_data, map_file)
                    
                    # Read the generated HTML file
                    if os.path.exists(map_file):
                        with open(map_file, 'r', encoding='utf-8') as f:
                            html_content = f.read()
                        
                        # Clean up temp file
                        try:
                            os.remove(map_file)
                        except:
                            pass
                            
                        # Add data source info to the HTML
                        html_content = html_content.replace(
                            '<body>',
                            '<body><div style="position:fixed;top:10px;right:10px;background:rgba(255,255,255,0.9);padding:8px;border-radius:5px;font-size:12px;z-index:10000;">📊 Dynamic Data from llload.py</div>'
                        )
                        
                        return html_content, 200, {'Content-Type': 'text/html'}
            except Exception as e:
                print(f"⚠️ llload.py map generation failed, using fallback: {e}")

        # Fallback to static HTML map
        matched_region = None
        for r in MUMBAI_REGIONS:
            if region.lower() in r.lower() or r.lower() in region.lower():
                matched_region = r
                break
        
        if not matched_region:
            return jsonify({
                "error": f"Region '{region}' not found",
                "available_regions": MUMBAI_REGIONS[:10]
            }), 404

        # Return enhanced static HTML map
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Evacuation Map - {matched_region}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                .map-container {{ border: 2px solid #007bff; padding: 20px; border-radius: 10px; background: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                .route {{ margin: 10px 0; padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #007bff; }}
                .high-risk {{ color: #dc3545; }}
                .moderate-risk {{ color: #fd7e14; }}
                .low-risk {{ color: #28a745; }}
                .data-source {{ position: fixed; top: 10px; right: 10px; background: rgba(255,193,7,0.9); padding: 8px 12px; border-radius: 5px; font-size: 12px; }}
                .header {{ text-align: center; color: #007bff; margin-bottom: 20px; }}
                .risk-badge {{ display: inline-block; padding: 5px 10px; border-radius: 15px; font-weight: bold; color: white; }}
            </style>
        </head>
        <body>
            <div class="data-source">📋 Static Fallback Data</div>
            <div class="map-container">
                <div class="header">
                    <h1>🗺️ Evacuation Map for {matched_region}</h1>
                    <p><strong>Current Risk Level:</strong> 
                       <span class="risk-badge {FLOOD_RISK_DATA.get(matched_region, 'moderate')}-risk">
                           {FLOOD_RISK_DATA.get(matched_region, 'moderate').upper()}
                       </span>
                    </p>
                </div>
                <h2>📍 Available Evacuation Routes:</h2>
        """
        
        routes = EVACUATION_ROUTES.get(matched_region, [
            {"destination": "Emergency Shelter 1", "distance_km": 8.5, "eta": "20 min", "risk_level": "low"},
            {"destination": "Emergency Shelter 2", "distance_km": 12.3, "eta": "28 min", "risk_level": "low"},
            {"destination": "Emergency Shelter 3", "distance_km": 15.7, "eta": "35 min", "risk_level": "low"}
        ])
        
        for i, route in enumerate(routes):
            html_content += f"""
                <div class="route">
                    <h3>🚗 Route {i+1}: To {route['destination']}</h3>
                    <p><strong>📏 Distance:</strong> {route['distance_km']} km</p>
                    <p><strong>⏱️ Estimated Time:</strong> {route['eta']}</p>
                    <p><strong>⚠️ Destination Risk:</strong> 
                       <span class="risk-badge {route['risk_level']}-risk">{route['risk_level'].upper()}</span>
                    </p>
                </div>
            """
        
        html_content += f"""
                <div style="margin-top: 30px; padding: 15px; background: #e3f2fd; border-radius: 8px;">
                    <h3>💡 Instructions:</h3>
                    <ul>
                        <li>Choose the route with the lowest risk level</li>
                        <li>Keep emergency contacts ready</li>
                        <li>Follow traffic updates and road conditions</li>
                        <li>Carry essential supplies and documents</li>
                    </ul>
                    <p><strong>🆘 Emergency Numbers:</strong> Fire: 101 | Police: 100 | Ambulance: 108</p>
                </div>
            </div>
            <script>
                console.log('Static evacuation map loaded for {matched_region}');
                // Auto-refresh every 5 minutes for updated data
                setTimeout(function() {{
                    location.reload();
                }}, 300000);
            </script>
        </body>
        </html>
        """
        
        return html_content, 200, {'Content-Type': 'text/html'}
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
