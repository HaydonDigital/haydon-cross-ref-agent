import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st

# Optional: PDF text extraction
try:
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True
except Exception:
    HAS_PYPDF2 = False

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


def split_parts_from_text(raw: str) -> list[str]:
    """
    Split pasted text into tokens. Handles:
    - newline-separated
    - comma-separated
    - space-separated
    """
    if not raw:
        return []
    tokens = re.split(r"[\n,;\t ]+", raw.strip())
    return [t.strip() for t in tokens if t.strip()]


def extract_text_from_pdf(uploaded_file) -> str:
    """Extract text from a PDF (text-based PDFs)."""
    if not HAS_PYPDF2:
        return ""

    reader = PdfReader(uploaded_file)
    chunks = []
    for page in reader.pages:
        txt = page.extract_text() or ""
        chunks.append(txt)
    return "\n".join(chunks)


def extract_part_candidates_from_pdf_text(text: str) -> list[str]:
    """
    Pull likely part-number-like strings from PDF text.

    Tune this regex to your catalog patterns.
    Current logic:
    - includes letters/numbers
    - allows -, /, ., #
    - 4 to 40 chars
    """
    if not text:
        return []

    # Example patterns often seen: PS-1100-AS-4-EG, TSN-802, P1000, etc.
    pattern = re.compile(r"\b[A-Z0-9][A-Z0-9\-\/\.\#]{3,39}\b", re.IGNORECASE)
    hits = pattern.findall(text)

    # Clean + dedupe while preserving order
    seen = set()
    out = []
    for h in hits:
        h2 = h.strip().strip(".,;:()[]{}")
        if len(h2) < 4:
            continue
        key = h2.upper()
        if key not in seen:
            seen.add(key)
            out.append(h2)
    return out


def get_haydon_candidates(part):
    """
    Generate progressive candidates for finding product images/submittals.
    Example: TSN-802 → TSN-802, TSN-80, TSN-8, TSN-800
    """
    part = str(part).upper()
    tokens = re.split(r"[ \-X()]+", part)

    for i in range(len(tokens), 0, -1):
        yield "-".join(tokens[:i])

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


def search_parts_contains(df, query: str):
    """Original behavior: contains search."""
    norm_query = normalize(query)
    return df[
        df["Normalized Haydon Part"].str.contains(norm_query, na=False)
        | df["Normalized Vendor Part"].str.contains(norm_query, na=False)
    ]


def search_parts_exact(df, query: str):
    """Exact match on normalized values (better for bulk)."""
    norm_query = normalize(query)
    if not norm_query:
        return df.iloc[0:0]
    return df[
        (df["Normalized Haydon Part"] == norm_query)
        | (df["Normalized Vendor Part"] == norm_query)
    ]


def bulk_search(cross_df: pd.DataFrame, parts: list[str], allow_contains_fallback: bool = True) -> pd.DataFrame:
    """
    Returns a flattened result table with one row per match.
    If no match: returns a single row indicating not found.
    """
    rows = []

    for raw in parts:
        raw = (raw or "").strip()
        if not raw:
            continue

        found = search_parts_exact(cross_df, raw)

        if found.empty and allow_contains_fallback:
            found = search_parts_contains(cross_df, raw)

        if found.empty:
            rows.append({
                "Input": raw,
                "Match Count": 0,
                "Status": "Not Found",
                "Vendor": None,
                "Vendor Part #": None,
                "Haydon Part Description": None,
                "Category": None,
            })
        else:
            for _, r in found.iterrows():
                rows.append({
                    "Input": raw,
                    "Match Count": len(found),
                    "Status": "Found",
                    "Vendor": r.get("Vendor"),
                    "Vendor Part #": r.get("Vendor Part #"),
                    "Haydon Part Description": r.get("Haydon Part Description"),
                    "Category": r.get("Category"),
                })

    return pd.DataFrame(rows)


# =========================================================
# STREAMLIT APP
# =========================================================
st.title("Haydon Cross-Reference Search")

try:
    cross_df = load_cross_reference()
    image_df = load_image_reference()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

tab_single, tab_bulk = st.tabs(["Single", "Bulk"])

# -------------------------
# SINGLE TAB (your existing behavior)
# -------------------------
with tab_single:
    query = st.text_input("Enter part number (Haydon or Vendor):")

    if query:
        results = search_parts_contains(cross_df, query)

        if not results.empty:
            st.subheader(f"Found {len(results)} matching entries")

            st.dataframe(
                results.drop(columns=["Normalized Haydon Part", "Normalized Vendor Part"], errors="ignore"),
                use_container_width=True
            )

            first_row = results.iloc[0]
            haydon_part = first_row["Haydon Part Description"]

            with st.sidebar:
                st.markdown("### Haydon Product Preview")
                match_found = False
                candidates = [haydon_part] + list(get_haydon_candidates(haydon_part))

                for candidate in candidates:
                    matched = image_df[image_df["Name_upper"].str.startswith(str(candidate).upper())]
                    if not matched.empty:
                        ref_row = matched.iloc[0]
                        image_url = ref_row.get("Cover Image")
                        submittal_url = ref_row.get("Files")
                        display_name = ref_row.get("Name")

                        if pd.notna(image_url):
                            st.image(image_url, caption=display_name, use_container_width=True)
                        if pd.notna(submittal_url):
                            st.markdown(f"[View Submittal for {display_name}]({submittal_url})")

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
                "marketing@haydoncorp.com."
            )
    else:
        st.write("Enter a part number above to begin.")

# -------------------------
# BULK TAB (new)
# -------------------------
with tab_bulk:
    st.markdown("Upload a PDF or paste a list of parts to cross-reference in bulk.")

    col1, col2 = st.columns(2)

    with col1:
        pasted = st.text_area(
            "Paste part numbers (one per line, or comma/space separated):",
            height=200,
            placeholder="Example:\nPS-1100-AS-4-EG\nTSN-802\nP1000"
        )

    with col2:
        pdf = st.file_uploader("Or upload a PDF:", type=["pdf"])
        allow_contains = st.checkbox("If exact match fails, try contains fallback (may increase false matches)", value=True)

    parts = []
    if pasted.strip():
        parts.extend(split_parts_from_text(pasted))

    if pdf is not None:
        pdf_text = extract_text_from_pdf(pdf)
        if not pdf_text:
            st.warning("Could not extract text from this PDF (it may be scanned).")
        else:
            candidates = extract_part_candidates_from_pdf_text(pdf_text)
            st.info(f"Extracted {len(candidates)} candidate tokens from the PDF.")
            # Optional: show extracted list for review
            with st.expander("View extracted candidates"):
                st.write(candidates)
            parts.extend(candidates)

    # Deduplicate inputs while preserving order
    seen = set()
    parts_unique = []
    for p in parts:
        key = p.strip().upper()
        if key and key not in seen:
            seen.add(key)
            parts_unique.append(p.strip())

    if st.button("Run Bulk Cross-Reference", type="primary", disabled=(len(parts_unique) == 0)):
        out_df = bulk_search(cross_df, parts_unique, allow_contains_fallback=allow_contains)

        st.subheader(f"Results ({len(out_df)} rows)")
        st.dataframe(out_df, use_container_width=True)

        # Summary
        found_count = int((out_df["Status"] == "Found").sum())
        not_found_count = int((out_df["Status"] == "Not Found").sum())
        st.write(f"Found rows: {found_count} | Not found rows: {not_found_count}")

        # Download CSV
        csv_bytes = out_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download results as CSV",
            data=csv_bytes,
            file_name="haydon_cross_reference_bulk_results.csv",
            mime="text/csv"
        )
