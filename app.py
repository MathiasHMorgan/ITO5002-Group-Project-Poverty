from pathlib import Path

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="Melbourne Food, Shelter & Charity Finder", layout="wide")
st.title("Melbourne Food, Shelter & Charity Finder")
st.caption("Proof of concept")

# Smaller Melbourne metro bbox
melbCoords = "(-38.30,144.75,-37.55,145.35)"
POPUP_TEMPLATE = Path("templates/popup.html").read_text(encoding="utf-8")

QUERY = f"""
[out:json][timeout:20];
(
  node["amenity"="social_facility"]["social_facility"="food_bank"]{melbCoords};
  node["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};
  node["office"="charity"]{melbCoords};
);
out body;
"""

OVERPASS_URLS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


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


def is_useless_row(row):
    return (
        row["name"] == "Unknown"
        and row["type"] == "Unknown"
        and row["address"] == "No address listed"
        and row["phone"] == "No phone listed"
        and row["website"] == "No website listed"
    )


@st.cache_data(ttl=86400)
def load_data():
    data = None
    last_error = None

    for url in OVERPASS_URLS:
        try:
            response = requests.get(
                url,
                params={"data": QUERY},
                timeout=60,
                headers={"User-Agent": "Streamlit Melbourne Support Finder"},
            )
            response.raise_for_status()
            data = response.json()
            break
        except requests.exceptions.RequestException as e:
            last_error = e

    if data is None:
        st.error(f"Could not load service data from Overpass: {last_error}")
        return pd.DataFrame()

    rows = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat")
        lon = el.get("lon")

        if lat is None or lon is None:
            continue

        rows.append(
            {
                "name": tags.get("name", "Unknown"),
                "type": classify(tags),
                "lat": lat,
                "lon": lon,
                "address": address_from_tags(tags),
                "phone": tags.get("phone", "No phone listed"),
                "website": tags.get("website", "No website listed"),
            }
        )

    df = pd.DataFrame(rows).drop_duplicates()

    if df.empty:
        return df

    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    df = df[~df.apply(is_useless_row, axis=1)].reset_index(drop=True)

    return df


df = load_data()

if df.empty:
    st.warning("No services found.")
    st.stop()

preferred_order = [
    "Food Bank",
    "Homeless Shelter",
    "Youth Shelter",
    "Women's Shelter",
    "Shelter",
    "Charity Organisation",
]

available_types = df["type"].dropna().unique().tolist()
service_types = [t for t in preferred_order if t in available_types]

if not service_types:
    st.warning("No valid service types found.")
    st.stop()

selected_type = st.selectbox("Filter by service type", service_types)
filtered_df = df[df["type"] == selected_type].reset_index(drop=True)

st.write(f"Showing **{len(filtered_df)}** services")

if filtered_df.empty:
    st.warning("No services found for this filter.")
    st.stop()

centre_lat = filtered_df["lat"].mean()
centre_lon = filtered_df["lon"].mean()

m = folium.Map(location=[centre_lat, centre_lon], zoom_start=11)

bounds = []
for _, row in filtered_df.iterrows():
    folium.Marker(
        location=[row["lat"], row["lon"]],
        popup=folium.Popup(popup_html(row), max_width=300),
        tooltip=row["name"],
    ).add_to(m)
    bounds.append([row["lat"], row["lon"]])

if bounds:
    m.fit_bounds(bounds)

st_folium(m, width=None, height=700)

st.subheader(f"Service List – {selected_type}")
st.dataframe(
    filtered_df[["name", "type", "address", "phone", "website"]],
    width="stretch",
    hide_index=True,
)