from pathlib import Path

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="Melbourne Food, Shelter & Charity Finder", layout="wide")
st.title("Melbourne Food, Shelter & Charity Finder")
st.caption("Proof of concept")

melbCoords = "(-38.5,144.2,-37.3,145.8)"
POPUP_TEMPLATE = Path("templates/popup.html").read_text(encoding="utf-8")

QUERY = f"""
[out:json][timeout:45];
(
  node["amenity"="social_facility"]["social_facility"="food_bank"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="food_bank"]{melbCoords};
  relation["amenity"="social_facility"]["social_facility"="food_bank"]{melbCoords};

  node["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};
  relation["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};

  node["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};
  relation["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};

  node["office"="charity"]{melbCoords};
  way["office"="charity"]{melbCoords};
  relation["office"="charity"]{melbCoords};
);
out center;
"""


def clean(value, fallback):
    return fallback if pd.isna(value) or str(value).strip() == "" else str(value)


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


def address_from_tags(tags):
    parts = [tags.get(k, "") for k in ["addr:housenumber", "addr:street", "addr:suburb", "addr:postcode"]]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else "No address listed"


def popup_html(row):
    website = clean(row["website"], "No website listed")
    website_html = f'<a href="{website}" target="_blank">{website}</a>' if website != "No website listed" else website
    return POPUP_TEMPLATE.format(
        name=clean(row["name"], "Unknown"),
        type=clean(row["type"], "Unknown"),
        address=clean(row["address"], "No address listed"),
        phone=clean(row["phone"], "No phone listed"),
        website_html=website_html,
    )


@st.cache_data(ttl=86400)
def load_data():
    response = requests.get(
        "https://overpass-api.de/api/interpreter",
        params={"data": QUERY},
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()

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
        })

    df = pd.DataFrame(rows).drop_duplicates()
    if df.empty:
        return df

    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    return df.dropna(subset=["lat", "lon"]).reset_index(drop=True)


df = load_data()

if df.empty:
    st.warning("No services found.")
    st.stop()

service_types = ["All"] + sorted(df["type"].dropna().unique())
selected_type = st.selectbox("Filter by service type", service_types)
filtered_df = df if selected_type == "All" else df[df["type"] == selected_type]

st.write(f"Showing **{len(filtered_df)}** services")

m = folium.Map(location=[-37.8136, 144.9631], zoom_start=10)

for _, row in filtered_df.iterrows():
    folium.Marker(
        location=[row["lat"], row["lon"]],
        popup=folium.Popup(popup_html(row), max_width=300),
        tooltip=row["name"],
    ).add_to(m)

st_folium(m, width=1000, height=500)

st.subheader("Service List – All Services" if selected_type == "All" else f"Service List – {selected_type}")
st.dataframe(
    filtered_df[["name", "type", "address", "phone", "website"]],
    width="stretch",
    hide_index=True,
)