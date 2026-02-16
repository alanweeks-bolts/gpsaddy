#!/usr/bin/env python3
"""Convert a KML file to a CSV of addresses using geopy reverse geocoding."""

import argparse
import csv
import sys
import time
import xml.etree.ElementTree as ET

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

KML_NS = {
    "kml": "http://www.opengis.net/kml/2.2",
    "gx": "http://www.google.com/kml/ext/2.2",
}


def parse_kml(filepath):
    """Parse a KML file and extract placemarks with coordinates.

    Returns a list of dicts with keys: name, latitude, longitude, (altitude).
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Detect namespace — some KML files omit the namespace
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    placemarks = root.iter(f"{ns}Placemark")
    results = []

    for pm in placemarks:
        name_el = pm.find(f"{ns}name")
        name = name_el.text.strip() if name_el is not None and name_el.text else ""

        # Look for coordinates in Point, LineString, or direct child
        coords_text = None
        for tag in ("Point", "LineString", "MultiGeometry"):
            container = pm.find(f".//{ns}{tag}")
            if container is not None:
                coord_el = container.find(f".//{ns}coordinates")
                if coord_el is not None and coord_el.text:
                    coords_text = coord_el.text.strip()
                    break

        if coords_text is None:
            coord_el = pm.find(f".//{ns}coordinates")
            if coord_el is not None and coord_el.text:
                coords_text = coord_el.text.strip()

        if not coords_text:
            continue

        # KML coordinates are lon,lat[,alt] separated by whitespace
        for coord_group in coords_text.split():
            parts = coord_group.strip().split(",")
            if len(parts) < 2:
                continue
            lon, lat = float(parts[0]), float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 else None
            results.append({
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "altitude": alt,
            })

    return results


def reverse_geocode(lat, lon, geolocator, retries=3):
    """Reverse-geocode a lat/lon pair into an address string."""
    for attempt in range(retries):
        try:
            location = geolocator.reverse((lat, lon), exactly_one=True, timeout=10)
            if location:
                return location.address
            return ""
        except GeocoderTimedOut:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  Warning: Timed out for ({lat}, {lon})", file=sys.stderr)
                return ""
        except GeocoderServiceError as e:
            print(f"  Warning: Geocoder error for ({lat}, {lon}): {e}", file=sys.stderr)
            return ""


def convert(input_path, output_path, deduplicate=True):
    """Read a KML file, reverse-geocode each point, and write a CSV."""
    print(f"Parsing {input_path} ...")
    points = parse_kml(input_path)

    if not points:
        print("No coordinates found in the KML file.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(points)} coordinate(s). Reverse-geocoding ...")

    geolocator = Nominatim(user_agent="gpsaddy-kml-converter")

    seen = set()
    rows = []
    for i, pt in enumerate(points, 1):
        key = (round(pt["latitude"], 6), round(pt["longitude"], 6))
        if deduplicate and key in seen:
            continue
        seen.add(key)

        print(f"  [{i}/{len(points)}] ({pt['latitude']}, {pt['longitude']}) ...", end=" ")
        address = reverse_geocode(pt["latitude"], pt["longitude"], geolocator)
        print(address or "(no address found)")

        rows.append({
            "name": pt["name"],
            "latitude": pt["latitude"],
            "longitude": pt["longitude"],
            "address": address,
        })

        # Respect Nominatim's 1 req/sec policy
        time.sleep(1.1)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "latitude", "longitude", "address"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} row(s) to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert a KML file to a CSV of addresses."
    )
    parser.add_argument("input", help="Path to the input KML file")
    parser.add_argument(
        "-o", "--output",
        help="Path to the output CSV file (default: <input>.csv)",
    )
    parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="Keep duplicate coordinates instead of deduplicating",
    )
    args = parser.parse_args()

    output = args.output
    if not output:
        output = args.input.rsplit(".", 1)[0] + ".csv"

    convert(args.input, output, deduplicate=not args.allow_duplicates)


if __name__ == "__main__":
    main()
