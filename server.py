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

# Try to import llload.py functionality
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
    print("📝 llload.py is required. Static fallback is disabled.")
    LLLOAD_AVAILABLE = False

app = Flask(__name__)
CORS(app)

# Mumbai regions data (from your CSV)
MUMBAI_REGIONS = [
    "Andheri East", "Andheri West", "Bandra East", "Bandra West", 
    "Colaba", "Fort", "Dadar", "Worli", "Powai", "Borivali",
    "Malad", "Goregaon", "Versova", "Juhu", "Santacruz", "Khar",
    "Mahim", "Sion", "Kurla", "Ghatkopar", "Thane", "Mulund"
]

# Static fallbacks removed: service now requires llload.py

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
        "status": "✅ Backend Only - Uses llload.py exclusively",
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
        "data_source": "Dynamic (llload.py) only"
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
            "message": "⚠️ llload.py not available"
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
        
        if not LLLOAD_AVAILABLE:
            return jsonify({
                "error": "llload.py is not available. This endpoint requires llload.py",
                "ward": matched_region
            }), 503

        return jsonify({
            "ward": matched_region,
            "message": "Flood prediction via llload.py not implemented",
            "llload_required": True
        }), 501
        
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
        
        if not LLLOAD_AVAILABLE:
            return jsonify({
                "error": "llload.py is not available. This endpoint requires llload.py",
            }), 503

        try:
            matched_region, match_score, routes_data = get_k_nearest_low_risk_routes(
                region, G, flood_df, k=route_count
            )

            if not matched_region:
                return jsonify({
                    "error": f"Region '{region}' not found",
                    "matched_region": None
                }), 404

            if not routes_data:
                return jsonify({
                    "error": f"No evacuation routes found for '{matched_region}'",
                    "matched_region": matched_region
                }), 404

            routes = []
            for route in routes_data:
                routes.append({
                    "destination": route['dest_region'],
                    "distance_km": route['distance_km'],
                    "eta": f"{route['eta_min']:.1f} min",
                    "risk_level": "low",
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
            return jsonify({
                "error": str(e),
                "message": "llload.py route computation failed"
            }), 500
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "matched_region": region if 'region' in locals() else "unknown"
        }), 500

@app.route("/map")
def map_page():
    """Generate evacuation map using llload.py"""
    try:
        region = request.args.get("region", "")
        if not region:
            return jsonify({"error": "Region parameter is required"}), 400

        if not LLLOAD_AVAILABLE:
            return jsonify({"error": "llload.py is not available. This endpoint requires llload.py"}), 503

        try:
            matched_region, match_score, routes_data = get_k_nearest_low_risk_routes(
                region, G, flood_df, k=ROUTE_COUNT
            )

            if not matched_region:
                return jsonify({
                    "error": f"Region '{region}' not found",
                    "matched_region": None
                }), 404

            if not routes_data:
                return jsonify({
                    "error": f"No evacuation routes found for '{matched_region}'",
                    "matched_region": matched_region
                }), 404

            map_file = f"temp_evacuation_map_{matched_region.replace(' ', '_')}.html"
            build_and_save_map(matched_region, routes_data, map_file)

            if os.path.exists(map_file):
                with open(map_file, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                try:
                    os.remove(map_file)
                except:
                    pass

                html_content = html_content.replace(
                    '<body>',
                    '<body><div style="position:fixed;top:10px;right:10px;background:rgba(255,255,255,0.9);padding:8px;border-radius:5px;font-size:12px;z-index:10000;">📊 Dynamic Data from llload.py</div>'
                )

                return html_content, 200, {'Content-Type': 'text/html'}

            return jsonify({"error": "Map file generation failed"}), 500
        except Exception as e:
            return jsonify({
                "error": str(e),
                "message": "llload.py map generation failed"
            }), 500
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
