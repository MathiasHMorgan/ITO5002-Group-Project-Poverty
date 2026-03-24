from pathlib import Path

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

from popup_utils import build_popup_html

st.set_page_config(page_title="Melbourne Overnight Support Finder", layout="wide")
st.title("Melbourne Overnight Support Finder")
st.caption("Find nearby support services in Melbourne.")

st.error(
    "Need help tonight?\n\n"
    "• Homelessness / urgent accommodation: 1800 825 955\n"
    "• Family violence support (Safe Steps): 1800 015 188\n"
    "• Emergency: 000"
)

col1, col2 = st.columns(2)
with col1:
    st.link_button("Get help now", "https://services.dffh.vic.gov.au/getting-help")
with col2:
    st.link_button("Safe Steps 24/7", "https://safesteps.org.au/")

st.caption(
    "This map is for support and wayfinding only. Availability, opening hours and safety conditions can change. "
    "Call first where possible."
)

melbCoords = "(-38.40,144.60,-37.45,145.50)"

OSM_QUERY = f"""
[out:json][timeout:25];
(
  node["amenity"="social_facility"]["social_facility"="food_bank"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="food_bank"]{melbCoords};

  node["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};

  node["office"="charity"]{melbCoords};
  way["office"="charity"]{melbCoords};
);
out center;
"""

OVERPASS_URLS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

HELPING_OUT_URL = (
    "https://data.melbourne.vic.gov.au/api/explore/v2.1/catalog/datasets/"
    "free-and-cheap-support-services-with-opening-hours-public-transport-and-parking-/records"
)

PUBLIC_TOILETS_URL = "https://data.melbourne.vic.gov.au/api/v2/catalog/datasets/public-toilets/exports/json"


def address_from_tags(tags):
    parts = [tags.get(k, "") for k in ["addr:housenumber", "addr:street", "addr:suburb", "addr:postcode"]]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else "No address listed"


def classify(tags):
    social = tags.get("social_facility", "")
    office = tags.get("office", "")
    social_for = str(tags.get("social_facility:for", "")).lower()
    text = f"{tags.get('name', '')} {tags.get('description', '')}".lower()

    if social == "food_bank":
        return "Food Bank"
    if social == "shelter":
        if "homeless" in social_for:
            return "Homeless Shelter"
        if "juvenile" in social_for or "youth" in text:
            return "Youth Shelter"
        if "woman" in social_for or any(
            x in text for x in ["domestic violence", "family violence", "women's refuge", "womens refuge"]
        ):
            return "Women's Shelter"
        return "Shelter"
    if office == "charity":
        return "Charity Organisation"

    return "Unknown"


def is_useless_row(row):
    return (
        row["name"] == "Unknown"
        and row["type"] == "Unknown"
        and row["address"] == "No address listed"
        and row["phone"] == "No phone listed"
        and row["website"] == "No website listed"
    )


@st.cache_data(ttl=86400)
def load_osm_data():
    data = None
    last_error = None

    for url in OVERPASS_URLS:
        try:
            response = requests.get(
                url,
                params={"data": OSM_QUERY},
                timeout=60,
                headers={"User-Agent": "Streamlit Melbourne Support Finder"},
            )
            response.raise_for_status()
            data = response.json()
            break
        except requests.exceptions.RequestException as e:
            last_error = e

    if data is None:
        st.error(f"Could not load OSM service data: {last_error}")
        return pd.DataFrame()

    rows = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")

        if lat is None or lon is None:
            continue

        rows.append({
            "name": tags.get("name", "Unknown"),
            "type": classify(tags),
            "lat": lat,
            "lon": lon,
            "address": address_from_tags(tags),
            "phone": tags.get("phone", "No phone listed"),
            "website": tags.get("website", "No website listed"),
            "hours": "",
            "public_transport": "",
            "source": "OSM",
        })

    df = pd.DataFrame(rows).drop_duplicates()
    if df.empty:
        return df

    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    df = df[~df.apply(is_useless_row, axis=1)].reset_index(drop=True)
    return df


@st.cache_data(ttl=86400)
def load_helping_out_data():
    all_rows = []
    offset = 0
    limit = 100

    while True:
        response = requests.get(
            HELPING_OUT_URL,
            params={"limit": limit, "offset": offset},
            timeout=60,
            headers={"User-Agent": "Streamlit Melbourne Support Finder"},
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", [])

        if not results:
            break

        all_rows.extend(results)

        if len(results) < limit:
            break

        offset += limit

    df = pd.DataFrame(all_rows)
    if df.empty:
        return df

    df["name"] = df["name"].fillna("Unknown")
    df["type"] = "Helping Out Services"
    df["address"] = (
        df[["address_1", "address_2", "suburb"]]
        .fillna("")
        .agg(", ".join, axis=1)
        .str.replace(r"(,\s*)+", ", ", regex=True)
        .str.strip(", ")
    )
    df["address"] = df["address"].replace("", "No address listed")
    df["phone"] = df["phone"].fillna("No phone listed")
    df["website"] = df["website"].fillna("No website listed")
    df["hours"] = df["opening_hours"].fillna("") if "opening_hours" in df.columns else ""
    df["public_transport"] = df["tram_routes"].fillna("") if "tram_routes" in df.columns else ""
    df["lat"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["lon"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["source"] = "City of Melbourne Helping Out"

    keep_cols = ["name", "type", "lat", "lon", "address", "phone", "website", "hours", "public_transport", "source"]
    df = df[keep_cols].dropna(subset=["lat", "lon"]).drop_duplicates().reset_index(drop=True)
    return df


@st.cache_data(ttl=86400)
def load_sanitation_data():
    try:
        response = requests.get(
            PUBLIC_TOILETS_URL,
            timeout=60,
            headers={"User-Agent": "Streamlit Melbourne Support Finder"},
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Could not load sanitation data: {e}")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    if df.empty:
        return df

    lat_col = next((c for c in ["latitude", "Latitude", "lat"] if c in df.columns), None)
    lon_col = next((c for c in ["longitude", "Longitude", "lon", "lng"] if c in df.columns), None)

    if lat_col is None or lon_col is None:
        st.error(f"Could not find sanitation dataset coordinates. Columns found: {list(df.columns)}")
        return pd.DataFrame()

    df["lat"] = pd.to_numeric(df[lat_col], errors="coerce")
    df["lon"] = pd.to_numeric(df[lon_col], errors="coerce")
    df["name"] = df["name"].fillna("Public Toilet") if "name" in df.columns else "Public Toilet"
    df["address"] = df["address"].fillna("No address listed") if "address" in df.columns else "No address listed"
    df["type"] = "Sanitation"
    df["phone"] = "No phone listed"
    df["website"] = "No website listed"
    df["hours"] = ""
    df["public_transport"] = ""
    df["source"] = "City of Melbourne Public Toilets"

    keep_cols = ["name", "type", "lat", "lon", "address", "phone", "website", "hours", "public_transport", "source"]
    df = df[keep_cols].dropna(subset=["lat", "lon"]).drop_duplicates().reset_index(drop=True)
    return df


osm_df = load_osm_data()
helping_out_df = load_helping_out_data()
sanitation_df = load_sanitation_data()

filter_options = [
    "Food Bank",
    "Homeless Shelter",
    "Youth Shelter",
    "Women's Shelter",
    "Shelter",
    "Charity Organisation",
    "Helping Out Services",
    "Sanitation",
]

available_filters = []

if not osm_df.empty:
    osm_types = set(osm_df["type"].dropna().unique().tolist())
    available_filters.extend([f for f in filter_options[:6] if f in osm_types])

if not helping_out_df.empty:
    available_filters.append("Helping Out Services")

if not sanitation_df.empty:
    available_filters.append("Sanitation")

if not available_filters:
    st.warning("No services found.")
    st.stop()

selected_type = st.selectbox("Filter by service type", available_filters)

if selected_type == "Helping Out Services":
    filtered_df = helping_out_df.copy()
elif selected_type == "Sanitation":
    filtered_df = sanitation_df.copy()
else:
    filtered_df = osm_df[osm_df["type"] == selected_type].reset_index(drop=True)

st.write(f"Showing **{len(filtered_df)}** locations")

if filtered_df.empty:
    st.warning("No locations found for this filter.")
    st.stop()

centre_lat = filtered_df["lat"].mean()
centre_lon = filtered_df["lon"].mean()

m = folium.Map(location=[centre_lat, centre_lon], zoom_start=12)

bounds = []
for _, row in filtered_df.iterrows():
    folium.Marker(
        location=[row["lat"], row["lon"]],
        popup=folium.Popup(build_popup_html(row), max_width=320),
        tooltip=row["name"],
    ).add_to(m)
    bounds.append([row["lat"], row["lon"]])

if bounds:
    m.fit_bounds(bounds)

st_folium(m, width=None, height=720)

st.subheader(f"Service List – {selected_type}")
st.dataframe(
    filtered_df[["name", "type", "address", "phone", "website"]],
    width="stretch",
    hide_index=True,
)