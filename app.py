import folium
import pandas as pd
import requests
import streamlit as st
import sqlite3
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from popup_utils import build_popup_html
from datetime import datetime

st.set_page_config(page_title="Melbourne Food, Sanitation and Shelter Finder", layout="wide")

# ---------- Page header ----------
st.title("Melbourne Food, Sanitation and Shelter Finder")
st.caption("Find nearby food, shelter, sanitation and community support services in Melbourne.")

# ---------- Urgent help ----------
st.markdown("## Need help tonight?")

c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    with st.container(border=True):
        st.markdown("### 🛏️ Accommodation")
        st.write("**1800 825 955**")
        st.caption("Homelessness / urgent accommodation")

with c2:
    with st.container(border=True):
        st.markdown("### 🛡️ Family Violence")
        st.write("**1800 015 188**")
        st.caption("Family violence support")

with c3:
    with st.container(border=True):
        st.markdown("### 🚨 Emergency")
        st.write("**000**")
        st.caption("Immediate danger or emergency")

with c4:
    with st.container(border=True):
        st.markdown("### 💊 Drugs / Alcohol")
        st.write("**211**")
        st.caption("Free call for food, housing and support services")

with c5:
    with st.container(border=True):
        st.markdown("### 🥫 Food")
        st.write("**211**")
        st.caption("Free call for food, housing and support services")

st.caption(
    "This map is for support and wayfinding only. Availability, opening hours and safety conditions can change. "
    "Call first where possible."
)

# ---------- Config ----------
melbCoords = "(-38.40,144.60,-37.45,145.50)"

OSM_QUERY = f"""
[out:json][timeout:25];
(
  node["amenity"="social_facility"]["social_facility"="food_bank"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="food_bank"]{melbCoords};

  node["amenity"="social_facility"]["social_facility"="soup_kitchen"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="soup_kitchen"]{melbCoords};

  node["amenity"="food_sharing"]{melbCoords};
  way["amenity"="food_sharing"]{melbCoords};

  node["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};

  node["amenity"="social_facility"]["social_facility"="group_home"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="group_home"]{melbCoords};

  node["office"="charity"]{melbCoords};
  way["office"="charity"]{melbCoords};

  node["amenity"="place_of_worship"]{melbCoords};
  way["amenity"="place_of_worship"]{melbCoords};

  node["amenity"="community_centre"]{melbCoords};
  way["amenity"="community_centre"]{melbCoords};
);
out center;
"""

OVERPASS_URLS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

PUBLIC_TOILETS_URL = "https://data.melbourne.vic.gov.au/api/v2/catalog/datasets/public-toilets/exports/json"

HELPING_OUT_URL = (
    "https://data.melbourne.vic.gov.au/api/explore/v2.1/catalog/datasets/"
    "free-and-cheap-support-services-with-opening-hours-public-transport-and-parking-/records"
)

TYPE_ORDER = [
    "Food Bank",
    "Shelter / Accommodation",
    "Youth Shelter",
    "Women's Shelter",
    "Support Services",
    "Charity Organisation",
    "Religious / Community Support",
    "Sanitation",
]

TYPE_TO_ICON = {
    "Food Bank": ("green", "cutlery"),
    "Shelter / Accommodation": ("red", "home"),
    "Youth Shelter": ("cadetblue", "home"),
    "Women's Shelter": ("pink", "heart"),
    "Support Services": ("darkblue", "plus"),
    "Charity Organisation": ("blue", "info-sign"),
    "Religious / Community Support": ("purple", "plus"),
    "Sanitation": ("orange", "tint"),
}

DB_PATH = "community_food_support.db"


def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS food_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            phone TEXT,
            website TEXT,
            notes TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

def geocode_address(address: str):
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": f"{address}, Melbourne, Victoria, Australia",
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "au",
            },
            timeout=20,
            headers={"User-Agent": "Melbourne Support Finder"},
        )
        response.raise_for_status()
        results = response.json()

        if not results:
            return None, None

        return float(results[0]["lat"]), float(results[0]["lon"])

    except requests.exceptions.RequestException:
        return None, None

def address_from_tags(tags):
    parts = [tags.get(k, "") for k in ["addr:housenumber", "addr:street", "addr:suburb", "addr:postcode"]]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else "No address listed"


def classify(tags):
    social = tags.get("social_facility", "")
    office = tags.get("office", "")
    amenity = tags.get("amenity", "")
    social_for = str(tags.get("social_facility:for", "")).lower()

    text = " ".join([
        str(tags.get("name", "")),
        str(tags.get("description", "")),
        str(tags.get("operator", "")),
        str(tags.get("website", "")),
        str(tags.get("denomination", "")),
    ]).lower()

    food_keywords = [
        "food", "meal", "meals", "pantry", "soup", "kitchen", "relief",
        "groceries", "parcel", "breakfast", "lunch", "dinner",
        "fareshare", "secondbite", "ozharvest", "community meal"
    ]

    support_keywords = [
        "community", "care", "mission", "relief", "outreach", "parish",
        "salvation army", "st vincent de paul", "vinnies", "wesley",
        "anglicare", "unitingcare", "baptcare",
    ]

    dv_keywords = [
        "domestic violence",
        "family violence",
        "women's refuge",
        "womens refuge",
        "safe steps",
        "violence support",
    ]

    drug_alcohol_keywords = [
        "drug",
        "alcohol",
        "aod",
        "addiction",
        "rehab",
        "rehabilitation",
        "substance",
        "detox",
    ]

    if social in {"food_bank", "soup_kitchen"}:
        return "Food Bank"

    if amenity == "food_sharing":
        return "Food Bank"

    if social in {"shelter", "group_home"}:
        if "juvenile" in social_for or "youth" in text:
            return "Youth Shelter"
        if "woman" in social_for or any(x in text for x in dv_keywords):
            return "Women's Shelter"
        return "Shelter / Accommodation"

    if office == "charity":
        if any(k in text for k in food_keywords):
            return "Food Bank"
        if any(k in text for k in drug_alcohol_keywords):
            return "Support Services"
        if any(k in text for k in dv_keywords):
            return "Women's Shelter"
        return "Charity Organisation"

    if amenity == "community_centre":
        if any(k in text for k in food_keywords):
            return "Food Bank"
        if any(k in text for k in drug_alcohol_keywords):
            return "Support Services"
        if any(k in text for k in dv_keywords):
            return "Women's Shelter"
        return "Unknown"

    if amenity == "place_of_worship":
        if any(k in text for k in food_keywords):
            return "Food Bank"
        if any(k in text for k in drug_alcohol_keywords):
            return "Support Services"
        if any(k in text for k in dv_keywords):
            return "Women's Shelter"
        if any(k in text for k in support_keywords):
            return "Religious / Community Support"
        return "Unknown"

    return "Unknown"

def is_useless_row(row):
    return (
        row["name"] == "Unknown"
        and row["type"] == "Unknown"
        and row["address"] == "No address listed"
        and row["phone"] == "No phone listed"
        and row["website"] == "No website listed"
    )

def marker_style(service_type):
    return TYPE_TO_ICON.get(service_type, ("gray", "info-sign"))


def marker_style_for_row(row):
    if row.get("source") == "Community food offer":
        return ("darkgreen", "star")
    return marker_style(row["type"])

@st.cache_data(ttl=30)
def load_custom_food_offers():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM food_offers", conn)
    conn.close()

    if df.empty:
        return df

    df["type"] = "Food Bank"
    df["hours"] = ""
    df["public_transport"] = ""
    df["source"] = "Community food offer"
    df["notes"] = df["notes"].fillna("Food support submitted through the app.")
    df["address"] = df["address"].fillna("No address listed")
    df["phone"] = df["phone"].fillna("No phone listed")
    df["website"] = df["website"].fillna("No website listed")

    keep_cols = [
        "name", "type", "lat", "lon", "address", "phone",
        "website", "hours", "public_transport", "source", "notes"
    ]
    return df[keep_cols].dropna(subset=["lat", "lon"]).drop_duplicates().reset_index(drop=True)

@st.cache_data(ttl=86400)
def load_osm_data():
    data = None
    errors = []

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
            errors.append(f"{url} -> {e}")

    if data is None:
        st.error("Could not load OSM service data from any Overpass endpoint.")
        with st.expander("Show endpoint errors"):
            for err in errors:
                st.write(err)
        return pd.DataFrame()

    rows = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")

        if lat is None or lon is None:
            continue

        service_type = classify(tags)
        address = address_from_tags(tags)
        phone = tags.get("phone", "No phone listed")
        website = tags.get("website", "No website listed")
        name = tags.get("name", "Unknown")

        note = ""

        if service_type == "Religious / Community Support":
            has_name = name != "Unknown"
            has_address = address != "No address listed"
            has_phone = phone != "No phone listed"

            if not has_name or not (has_address or has_phone):
                continue

            note = "Religious or community-linked venue. Support availability is not guaranteed; contact directly where possible."

        rows.append({
            "name": name,
            "type": service_type,
            "lat": lat,
            "lon": lon,
            "address": address,
            "phone": phone,
            "website": website,
            "hours": "",
            "public_transport": "",
            "source": "OSM",
            "notes": note,
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
def load_helping_out_food_data():
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

    text_cols = [
        c for c in [
            "name",
            "what",
            "who",
            "category_1",
            "category_2",
            "category_3",
            "category_4",
            "category_5",
            "category_6",
        ] if c in df.columns
    ]

    if not text_cols:
        return pd.DataFrame()

    df["search_text"] = (
        df[text_cols]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )

    food_keywords = [
        "food", "meal", "meals", "breakfast", "lunch", "dinner",
        "soup", "kitchen", "pantry", "groceries", "food parcel",
        "food bank", "relief", "voucher", "community meal"
    ]

    df = df[df["search_text"].apply(lambda x: any(k in x for k in food_keywords))].copy()

    if df.empty:
        return df

    df["name"] = df["name"].fillna("Unknown") if "name" in df.columns else "Unknown"

    address_cols = [c for c in ["address_1", "address_2", "suburb"] if c in df.columns]
    if address_cols:
        df["address"] = (
            df[address_cols]
            .fillna("")
            .agg(", ".join, axis=1)
            .str.replace(r"(,\s*)+", ", ", regex=True)
            .str.strip(", ")
        )
        df["address"] = df["address"].replace("", "No address listed")
    else:
        df["address"] = "No address listed"

    df["phone"] = df["phone"].fillna("No phone listed") if "phone" in df.columns else "No phone listed"
    df["website"] = df["website"].fillna("No website listed") if "website" in df.columns else "No website listed"
    df["hours"] = df["opening_hours"].fillna("") if "opening_hours" in df.columns else ""

    transport_cols = [c for c in ["tram_routes", "bus_routes", "nearest_train_station"] if c in df.columns]
    if transport_cols:
        df["public_transport"] = (
            df[transport_cols]
            .fillna("")
            .astype(str)
            .agg(" | ".join, axis=1)
            .str.replace(r"(\s*\|\s*)+", " | ", regex=True)
            .str.strip(" |")
        )
    else:
        df["public_transport"] = ""

    df["lat"] = pd.to_numeric(df["latitude"], errors="coerce") if "latitude" in df.columns else pd.NA
    df["lon"] = pd.to_numeric(df["longitude"], errors="coerce") if "longitude" in df.columns else pd.NA
    df = df.dropna(subset=["lat", "lon"]).copy()

    df["type"] = "Food Bank"
    df["source"] = "City of Melbourne Helping Out"
    df["notes"] = "Food-related support service from City of Melbourne Helping Out."

    keep_cols = [
        "name", "type", "lat", "lon", "address", "phone", "website",
        "hours", "public_transport", "source", "notes"
    ]
    df = df[keep_cols].drop_duplicates().reset_index(drop=True)

    return df

@st.cache_data(ttl=86400)
def load_helping_out_shelter_data():
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

    text_cols = [
        c for c in [
            "name",
            "what",
            "who",
            "category_1",
            "category_2",
            "category_3",
            "category_4",
            "category_5",
            "category_6",
        ] if c in df.columns
    ]

    if not text_cols:
        return pd.DataFrame()

    df["search_text"] = (
        df[text_cols]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )

    shelter_keywords = [
        "accommodation",
        "crisis accommodation",
        "homeless",
        "homelessness",
        "housing",
        "rough sleeping",
        "sleeping rough",
        "supported housing",
        "transitional housing",
        "night shelter",
        "rooming",
        "common ground",
        "launch housing",
        "house of welcome",
        "salvation army",
    ]

    df = df[df["search_text"].apply(lambda x: any(k in x for k in shelter_keywords))].copy()

    if df.empty:
        return df

    df["name"] = df["name"].fillna("Unknown") if "name" in df.columns else "Unknown"

    address_cols = [c for c in ["address_1", "address_2", "suburb"] if c in df.columns]
    if address_cols:
        df["address"] = (
            df[address_cols]
            .fillna("")
            .agg(", ".join, axis=1)
            .str.replace(r"(,\s*)+", ", ", regex=True)
            .str.strip(", ")
        )
        df["address"] = df["address"].replace("", "No address listed")
    else:
        df["address"] = "No address listed"

    df["phone"] = df["phone"].fillna("No phone listed") if "phone" in df.columns else "No phone listed"
    df["website"] = df["website"].fillna("No website listed") if "website" in df.columns else "No website listed"
    df["hours"] = df["opening_hours"].fillna("") if "opening_hours" in df.columns else ""

    transport_cols = [c for c in ["tram_routes", "bus_routes", "nearest_train_station"] if c in df.columns]
    if transport_cols:
        df["public_transport"] = (
            df[transport_cols]
            .fillna("")
            .astype(str)
            .agg(" | ".join, axis=1)
            .str.replace(r"(\s*\|\s*)+", " | ", regex=True)
            .str.strip(" |")
        )
    else:
        df["public_transport"] = ""

    df["lat"] = pd.to_numeric(df["latitude"], errors="coerce") if "latitude" in df.columns else pd.NA
    df["lon"] = pd.to_numeric(df["longitude"], errors="coerce") if "longitude" in df.columns else pd.NA
    df = df.dropna(subset=["lat", "lon"]).copy()

    df["type"] = "Shelter / Accommodation"
    df["source"] = "City of Melbourne Helping Out"
    df["notes"] = "Accommodation or homelessness-related support service from City of Melbourne Helping Out."

    keep_cols = [
        "name", "type", "lat", "lon", "address", "phone", "website",
        "hours", "public_transport", "source", "notes"
    ]
    df = df[keep_cols].drop_duplicates().reset_index(drop=True)

    return df

@st.cache_data(ttl=86400)
def load_helping_out_support_data():
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

    text_cols = [
        c for c in [
            "name",
            "what",
            "who",
            "category_1",
            "category_2",
            "category_3",
            "category_4",
            "category_5",
            "category_6",
        ] if c in df.columns
    ]

    if not text_cols:
        return pd.DataFrame()

    df["search_text"] = (
        df[text_cols]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )

    support_keywords = [
        "drug",
        "alcohol",
        "aod",
        "addiction",
        "detox",
        "rehab",
        "rehabilitation",
        "substance",
        "family violence",
        "domestic violence",
        "women's support",
        "womens support",
        "counselling",
        "counseling",
        "mental health",
        "wellbeing",
        "support",
        "social work",
        "needle and syringe",
        "crisis",
    ]

    exclude_keywords = [
        "food bank",
        "food parcel",
        "meal",
        "meals",
        "soup kitchen",
        "accommodation",
        "housing",
        "homeless",
        "homelessness",
        "rough sleeping",
        "sleeping rough",
    ]

    include_mask = df["search_text"].apply(lambda x: any(k in x for k in support_keywords))
    exclude_mask = df["search_text"].apply(lambda x: any(k in x for k in exclude_keywords))

    df = df[include_mask & ~exclude_mask].copy()

    if df.empty:
        return df

    df["name"] = df["name"].fillna("Unknown") if "name" in df.columns else "Unknown"

    address_cols = [c for c in ["address_1", "address_2", "suburb"] if c in df.columns]
    if address_cols:
        df["address"] = (
            df[address_cols]
            .fillna("")
            .agg(", ".join, axis=1)
            .str.replace(r"(,\s*)+", ", ", regex=True)
            .str.strip(", ")
        )
        df["address"] = df["address"].replace("", "No address listed")
    else:
        df["address"] = "No address listed"

    df["phone"] = df["phone"].fillna("No phone listed") if "phone" in df.columns else "No phone listed"
    df["website"] = df["website"].fillna("No website listed") if "website" in df.columns else "No website listed"
    df["hours"] = df["opening_hours"].fillna("") if "opening_hours" in df.columns else ""

    transport_cols = [c for c in ["tram_routes", "bus_routes", "nearest_train_station"] if c in df.columns]
    if transport_cols:
        df["public_transport"] = (
            df[transport_cols]
            .fillna("")
            .astype(str)
            .agg(" | ".join, axis=1)
            .str.replace(r"(\s*\|\s*)+", " | ", regex=True)
            .str.strip(" |")
        )
    else:
        df["public_transport"] = ""

    df["lat"] = pd.to_numeric(df["latitude"], errors="coerce") if "latitude" in df.columns else pd.NA
    df["lon"] = pd.to_numeric(df["longitude"], errors="coerce") if "longitude" in df.columns else pd.NA
    df = df.dropna(subset=["lat", "lon"]).copy()

    df["type"] = "Support Services"
    df["source"] = "City of Melbourne Helping Out"
    df["notes"] = "Drug, alcohol, family violence or general support service from City of Melbourne Helping Out."

    keep_cols = [
        "name", "type", "lat", "lon", "address", "phone", "website",
        "hours", "public_transport", "source", "notes"
    ]
    df = df[keep_cols].drop_duplicates().reset_index(drop=True)

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
    df["notes"] = "Public toilet location."

    keep_cols = [
        "name", "type", "lat", "lon", "address", "phone", "website",
        "hours", "public_transport", "source", "notes"
    ]
    df = df[keep_cols].dropna(subset=["lat", "lon"]).drop_duplicates().reset_index(drop=True)
    return df

@st.dialog("Offer food support")
def food_offer_dialog():
    with st.form("food_offer_form"):
        st.write("Add a restaurant, uni café, or other place offering food support.")

        name = st.text_input("Organisation / venue name*")
        address = st.text_input("Address*")
        phone = st.text_input("Phone")
        website = st.text_input("Website")
        notes = st.text_area("Notes", placeholder="e.g. free meals after 5pm on weekdays")

        submitted = st.form_submit_button("Submit")

        if submitted:
            if not name.strip():
                st.warning("Name is required.")
                return

            if not address.strip():
                st.warning("Address is required.")
                return

            lat, lon = geocode_address(address.strip())

            if lat is None or lon is None:
                st.warning("Could not find that address on the map. Please check the address and try again.")
                return

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO food_offers (name, address, phone, website, notes, lat, lon, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name.strip(),
                address.strip(),
                phone.strip(),
                website.strip(),
                notes.strip(),
                lat,
                lon,
                datetime.utcnow().isoformat()
            ))
            conn.commit()
            conn.close()

            st.cache_data.clear()
            st.session_state["selected_type"] = "Food Bank"
            st.success("Food provider added.")
            st.rerun()

# ---------- Data ----------
osm_df = load_osm_data()
helping_out_food_df = load_helping_out_food_data()
custom_food_df = load_custom_food_offers()
sanitation_df = load_sanitation_data()
helping_out_shelter_df = load_helping_out_shelter_data()
helping_out_support_df = load_helping_out_support_data()

available_filters = []

osm_types = set(osm_df["type"].dropna().unique().tolist()) if not osm_df.empty else set()

for f in TYPE_ORDER:
    if f == "Food Bank":
        if "Food Bank" in osm_types or not helping_out_food_df.empty or not custom_food_df.empty:
            available_filters.append(f)

    elif f == "Shelter / Accommodation":
        if "Shelter / Accommodation" in osm_types or not helping_out_shelter_df.empty:
            available_filters.append(f)

    elif f == "Support Services":
        support_osm_types = {"Charity Organisation", "Religious / Community Support", "Women's Shelter"}
        if any(t in osm_types for t in support_osm_types) or not helping_out_support_df.empty:
            available_filters.append(f)

    elif f == "Sanitation":
        if not sanitation_df.empty:
            available_filters.append(f)

    else:
        if f in osm_types:
            available_filters.append(f)

if not available_filters:
    st.warning("No services found.")
    st.stop()

# ---------- Quick actions ----------
st.subheader("Quick Actions")
qa1, qa2, qa3, qa4 = st.columns(4)

if qa1.button("Need food", use_container_width=True):
    st.session_state["selected_type"] = "Food Bank"
if qa2.button("Need shelter", use_container_width=True):
    st.session_state["selected_type"] = "Shelter / Accommodation"
if qa3.button("Need Sanitation", use_container_width=True):
    st.session_state["selected_type"] = "Sanitation"
if qa4.button("Need support", use_container_width=True):
    st.session_state["selected_type"] = "Support Services"

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Filters")

    default_type = st.session_state.get("selected_type", available_filters[0])
    if default_type not in available_filters:
        default_type = available_filters[0]

    selected_type = st.selectbox(
        "Filter by service type",
        available_filters,
        index=available_filters.index(default_type),
    )

    search_term = st.text_input(
        "Search within current filter",
        placeholder="e.g. Launch Housing, Salvation Army, Southbank"
    )

    show_only_phone = st.checkbox("Only show places with phone", value=False)
    show_only_website = st.checkbox("Only show places with website", value=False)
    show_only_address = st.checkbox("Only show places with address", value=False)

    st.divider()
    st.caption("Marker colours")
    for t in available_filters:
        if t in TYPE_TO_ICON:
            color, _ = marker_style(t)
            st.markdown(f"- **{t}**: {color}")

    st.divider()
    st.subheader("Offer food support")
    st.caption("Restaurants, cafés or organisations can add a food support location.")
    if st.button("Add food provider", use_container_width=True):
        food_offer_dialog()

# ---------- Filtered data ----------
if selected_type == "Sanitation":
    filtered_df = sanitation_df.copy()

elif selected_type == "Food Bank":
    osm_food_df = osm_df[osm_df["type"] == "Food Bank"].copy()
    filtered_df = pd.concat(
        [osm_food_df, helping_out_food_df, custom_food_df],
        ignore_index=True
    )

elif selected_type == "Shelter / Accommodation":
    osm_shelter_df = osm_df[osm_df["type"] == "Shelter / Accommodation"].copy()
    filtered_df = pd.concat([osm_shelter_df, helping_out_shelter_df], ignore_index=True)

elif selected_type == "Support Services":
    osm_support_df = osm_df[
        osm_df["type"].isin(["Charity Organisation", "Religious / Community Support", "Women's Shelter"])
    ].copy()
    filtered_df = pd.concat([osm_support_df, helping_out_support_df], ignore_index=True)

else:
    filtered_df = osm_df[osm_df["type"] == selected_type].reset_index(drop=True)

if not filtered_df.empty:
    filtered_df["name_key"] = filtered_df["name"].fillna("").str.strip().str.lower()
    filtered_df["lat_round"] = filtered_df["lat"].round(4)
    filtered_df["lon_round"] = filtered_df["lon"].round(4)

    filtered_df = (
        filtered_df
        .drop_duplicates(subset=["name_key", "lat_round", "lon_round"])
        .drop(columns=["name_key", "lat_round", "lon_round"])
        .reset_index(drop=True)
    )

if search_term:
    q = search_term.strip().lower()

    search_cols = ["name", "address", "phone", "website", "notes", "source"]
    mask = False

    for col in search_cols:
        if col in filtered_df.columns:
            mask = mask | filtered_df[col].fillna("").astype(str).str.lower().str.contains(q, na=False)

    filtered_df = filtered_df[mask].reset_index(drop=True)

# ---------- Summary metrics ----------
m1, m2, m3, m4 = st.columns(4)
m1.metric("Locations found", len(filtered_df))
m2.metric("With phone", int((filtered_df["phone"] != "No phone listed").sum()) if not filtered_df.empty else 0)
m3.metric("With website", int((filtered_df["website"] != "No website listed").sum()) if not filtered_df.empty else 0)
m4.metric("With address", int((filtered_df["address"] != "No address listed").sum()) if not filtered_df.empty else 0)

if filtered_df.empty:
    st.warning("No locations found for this filter.")
    st.stop()

st.write(f"Showing **{len(filtered_df)}** locations")

# ---------- Map ----------
centre_lat = filtered_df["lat"].mean()
centre_lon = filtered_df["lon"].mean()

m = folium.Map(location=[centre_lat, centre_lon], zoom_start=12)
cluster = MarkerCluster().add_to(m)

bounds = []
for _, row in filtered_df.iterrows():
    color, icon_name = marker_style_for_row(row)

    folium.Marker(
        location=[row["lat"], row["lon"]],
        popup=folium.Popup(build_popup_html(row), max_width=320),
        tooltip=row["name"],
        icon=folium.Icon(color=color, icon=icon_name),
    ).add_to(cluster)

    bounds.append([row["lat"], row["lon"]])

if bounds:
    m.fit_bounds(bounds)

st_folium(m, width=None, height=720)

# ---------- Results cards ----------
st.subheader(f"Results – {selected_type}")

for _, row in filtered_df.iterrows():
    website = row["website"]
    phone = row["phone"]
    notes = row.get("notes", "")

    with st.container(border=True):
        c1, c2 = st.columns([3, 1])

        with c1:
            st.markdown(f"### {row['name']}")
            st.caption(row["type"])
            if row.get("source") == "Community food offer":
                st.caption("Submitted via community form")
            st.write(f"**Address:** {row['address']}")
            st.write(f"**Phone:** {phone}")
            st.write(f"**Website:** {website}")
            if notes:
                st.caption(notes)

# ---------- Raw table ----------
with st.expander("Show raw table"):
    st.dataframe(
        filtered_df[["name", "type", "address", "phone", "website"]],
        width="stretch",
        hide_index=True,
    )