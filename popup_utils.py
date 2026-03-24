from pathlib import Path
import pandas as pd

POPUP_TEMPLATE = Path("templates/popup.html").read_text(encoding="utf-8")


def clean(value, fallback):
    return fallback if pd.isna(value) or str(value).strip() == "" else str(value)


def make_website_html(website: str) -> str:
    website = clean(website, "No website listed")
    return f'<a href="{website}" target="_blank">{website}</a>' if website != "No website listed" else website


def build_popup_html(row) -> str:
    return POPUP_TEMPLATE.format(
        name=clean(row.get("name"), "Unknown"),
        type=clean(row.get("type"), "Unknown"),
        address=clean(row.get("address"), "No address listed"),
        phone=clean(row.get("phone"), "No phone listed"),
        website_html=make_website_html(row.get("website")),
        hours=clean(row.get("hours"), "Not listed"),
        transport=clean(row.get("public_transport"), "Not listed"),
        source=clean(row.get("source"), "Source not listed"),
    )