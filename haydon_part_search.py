import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(layout="wide", page_title="Haydon Cross-Reference Search")

BASE_DIR = Path(__file__).parent
CROSS_FILE = BASE_DIR / "Updated File - 7-10-25.xlsx"
IMAGE_FILE = BASE_DIR / "Images.xlsx"


# =========================================================
# HELPERS
# =========================================================
def normalize(part):
    """Remove non-alphanumerics and lowercase for consistent matching."""
    if pd.isna(part):
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(part)).lower()


def get_haydon_candidates(part):
    """
    Generate progressive candidates for finding product images/submittals.
    Example: TSN-802 → TSN-802, TSN-80, TSN-8, TSN-800
    """
    part = str(part).upper()
    tokens = re.split(r"[ \-X()]+", part)

    # progressively truncate tokens
    for i in range(len(tokens), 0, -1):
        yield "-".join(tokens[:i])

    # simple generalization: numeric suffix rounding (TSN802 → TSN800)
    compact = part.replace("-", "")
    match = re.match(r"([A-Z\-]+)(\d{3,})$", compact)
    if match:
        prefix, number = match.groups()
        yield f"{prefix}{number[:2]}0"


# =========================================================
# DATA LOADERS
# =========================================================
@st.cache_data
def load_cross_reference():
    if not CROSS_FILE.exists():
        raise FileNotFoundError(f"Cross-reference file not found: {CROSS_FILE}")
    df = pd.read_excel(CROSS_FILE, sheet_name="Export", engine="openpyxl")
    df["Normalized Haydon Part"] = df["Haydon Part Description"].apply(normalize)
    df["Normalized Vendor Part"] = df["Vendor Part #"].apply(normalize)
    return df


@st.cache_data
def load_image_reference():
    if not IMAGE_FILE.exists():
        raise FileNotFoundError(f"Image/submittal file not found: {IMAGE_FILE}")
    df = pd.read_excel(IMAGE_FILE, sheet_name="Sheet1")
    df["Name_upper"] = df["Name"].astype(str).str.upper()
    return df


def search_parts(df, query):
    """Search normalized columns for the given query."""
    norm_query = normalize(query)
    return df[
        df["Normalized Haydon Part"].str.contains(norm_query, na=False)
        | df["Normalized Vendor Part"].str.contains(norm_query, na=False)
    ]


# =========================================================
# STREAMLIT APP
# =========================================================
st.title("Haydon Cross-Reference Search")

query = st.text_input("Enter part number (Haydon or Vendor):")

if query:
    try:
        cross_df = load_cross_reference()
        image_df = load_image_reference()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    results = search_parts(cross_df, query)

    if not results.empty:
        st.subheader(f"Found {len(results)} matching entries")

        # Drop helper columns from display
        st.dataframe(
            results.drop(columns=["Normalized Haydon Part", "Normalized Vendor Part"], errors="ignore"),
            use_container_width=True
        )

        first_row = results.iloc[0]
        haydon_part = first_row["Haydon Part Description"]

        # Sidebar image/submittal
        with st.sidebar:
            st.markdown("### Haydon Product Preview")
            match_found = False
            candidates = [haydon_part] + list(get_haydon_candidates(haydon_part))

            for candidate in candidates:
                matched = image_df[image_df["Name_upper"].str.startswith(candidate)]
                if not matched.empty:
                    ref_row = matched.iloc[0]
                    image_url = ref_row.get("Cover Image")
                    submittal_url = ref_row.get("Files")
                    display_name = ref_row.get("Name")

                    if pd.notna(image_url):
                        st.image(image_url, caption=display_name, use_container_width=True)
                    if pd.notna(submittal_url):
                        st.markdown(
                            f"[📄 View Submittal for {display_name}]({submittal_url})",
                            unsafe_allow_html=True,
                        )

                    if display_name != haydon_part:
                        st.info(f"Showing closest match: {display_name} (for {haydon_part})")
                    match_found = True
                    break

            if not match_found:
                st.warning("No product preview or submittal found for this Haydon part.")
    else:
        st.error(
            "Unable to find the cross reference you're looking for. "
            "Please send the Haydon and customer or competitive part numbers to "
            "[marketing@haydoncorp.com](mailto:marketing@haydoncorp.com)."
        )
else:
    st.write("Enter a part number above to begin.")
