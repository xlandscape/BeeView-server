import urllib.request, json

url = 'http://localhost:32000/geojson/viewport?min_lat=43.5&min_lng=1.0&max_lat=44.2&max_lng=2.2'
with urllib.request.urlopen(url) as r:
    d = json.load(r)

features = d.get('features', [])
print(f"Feature count: {len(features)}")
if features:
    f = features[0]
    print(f"Feature id: {f.get('id')}")
    print(f"Properties: {json.dumps(f.get('properties', {}), indent=2)}")
    coords = f.get('geometry', {}).get('coordinates', [])
    print(f"Geometry type: {f.get('geometry', {}).get('type')}")
    # Print first coordinate
    def first_coord(c):
        while isinstance(c, list) and isinstance(c[0], list):
            c = c[0]
        return c
    print(f"First coordinate: {first_coord(coords)}")
else:
    print("NO FEATURES - checking full geojson...")
    url2 = 'http://localhost:32000/geojson'
    with urllib.request.urlopen(url2) as r2:
        d2 = json.load(r2)
    features2 = d2.get('features', [])
    print(f"Full geojson count: {len(features2)}")
    if features2:
        f = features2[0]
        print(f"Feature id: {f.get('id')}")
        print(f"Properties: {json.dumps(f.get('properties', {}), indent=2)}")
        coords = f.get('geometry', {}).get('coordinates', [])
        def first_coord(c):
            while isinstance(c, list) and isinstance(c[0], list):
                c = c[0]
            return c
        print(f"First coordinate: {first_coord(coords)}")
