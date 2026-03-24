import folium
import pandas as pd
import requests
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from popup_utils import build_popup_html

st.set_page_config(page_title="Melbourne Overnight Support Finder", layout="wide")

# ---------- Page header ----------
st.title("Melbourne Overnight Support Finder")
st.caption("Find nearby food, shelter, sanitation and community support services in Melbourne.")

# ---------- Urgent help ----------
st.markdown("## Need help tonight?")

c1, c2, c3 = st.columns(3)

with c1:
    with st.container(border=True):
        st.markdown("### 🛏️ Accommodation")
        st.write("**1800 825 955**")
        st.caption("Homelessness / urgent accommodation")

with c2:
    with st.container(border=True):
        st.markdown("### 🛡️ Safe Steps")
        st.write("**1800 015 188**")
        st.caption("Family violence support")

with c3:
    with st.container(border=True):
        st.markdown("### 🚨 Emergency")
        st.write("**000**")
        st.caption("Immediate danger or emergency")
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

  node["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};
  way["amenity"="social_facility"]["social_facility"="shelter"]{melbCoords};

  node["office"="charity"]{melbCoords};
  way["office"="charity"]{melbCoords};

  node["amenity"="place_of_worship"]{melbCoords};
  way["amenity"="place_of_worship"]{melbCoords};
);
out center;
"""

OVERPASS_URLS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

PUBLIC_TOILETS_URL = "https://data.melbourne.vic.gov.au/api/v2/catalog/datasets/public-toilets/exports/json"

TYPE_ORDER = [
    "Food Bank",
    "Homeless Shelter",
    "Youth Shelter",
    "Women's Shelter",
    "Shelter",
    "Charity Organisation",
    "Religious / Community Support",
    "Sanitation",
]

TYPE_TO_ICON = {
    "Food Bank": ("green", "cutlery"),
    "Homeless Shelter": ("red", "home"),
    "Youth Shelter": ("cadetblue", "home"),
    "Women's Shelter": ("pink", "heart"),
    "Shelter": ("darkred", "home"),
    "Charity Organisation": ("blue", "info-sign"),
    "Religious / Community Support": ("purple", "plus"),
    "Sanitation": ("orange", "tint"),
}


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

    if amenity == "place_of_worship":
        support_keywords = [
            "community",
            "care",
            "mission",
            "relief",
            "outreach",
            "parish",
            "salvation army",
            "st vincent de paul",
            "vinnies",
            "wesley",
            "anglicare",
            "unitingcare",
            "baptcare",
        ]
        if any(keyword in text for keyword in support_keywords):
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


# ---------- Data ----------
osm_df = load_osm_data()
sanitation_df = load_sanitation_data()

available_filters = []

if not osm_df.empty:
    osm_types = set(osm_df["type"].dropna().unique().tolist())
    available_filters.extend([f for f in TYPE_ORDER[:7] if f in osm_types])

if not sanitation_df.empty:
    available_filters.append("Sanitation")

if not available_filters:
    st.warning("No services found.")
    st.stop()

# ---------- Quick actions ----------
st.subheader("Quick Actions")
qa1, qa2, qa3, qa4 = st.columns(4)

if qa1.button("Need food", use_container_width=True):
    st.session_state["selected_type"] = "Food Bank"
if qa2.button("Need shelter", use_container_width=True):
    st.session_state["selected_type"] = "Homeless Shelter" if "Homeless Shelter" in available_filters else "Shelter"
if qa3.button("Need toilet", use_container_width=True):
    st.session_state["selected_type"] = "Sanitation"
if qa4.button("Need support", use_container_width=True):
    if "Charity Organisation" in available_filters:
        st.session_state["selected_type"] = "Charity Organisation"

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

    show_only_phone = st.checkbox("Only show places with phone", value=False)
    show_only_website = st.checkbox("Only show places with website", value=False)
    show_only_address = st.checkbox("Only show places with address", value=False)

    st.divider()
    st.caption("Marker colours")
    for t in available_filters:
        if t in TYPE_TO_ICON:
            color, _ = marker_style(t)
            st.markdown(f"- **{t}**: {color}")

# ---------- Filtered data ----------
if selected_type == "Sanitation":
    filtered_df = sanitation_df.copy()
else:
    filtered_df = osm_df[osm_df["type"] == selected_type].reset_index(drop=True)

if show_only_phone:
    filtered_df = filtered_df[filtered_df["phone"] != "No phone listed"]

if show_only_website:
    filtered_df = filtered_df[filtered_df["website"] != "No website listed"]

if show_only_address:
    filtered_df = filtered_df[filtered_df["address"] != "No address listed"]

filtered_df = filtered_df.reset_index(drop=True)

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
    color, icon_name = marker_style(row["type"])

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
            st.write(f"**Address:** {row['address']}")
            st.write(f"**Phone:** {phone}")
            st.write(f"**Website:** {website}")
            if notes:
                st.caption(notes)

        with c2:
            st.metric("Lat", f"{row['lat']:.4f}")
            st.metric("Lon", f"{row['lon']:.4f}")

# ---------- Raw table ----------
with st.expander("Show raw table"):
    st.dataframe(
        filtered_df[["name", "type", "address", "phone", "website"]],
        width="stretch",
        hide_index=True,
    )