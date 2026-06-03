import io
import json
import os
from typing import Dict, List, Optional
import streamlit as st
import requests
import re
import pandas as pd  # Added pandas for easy CSV manipulation

token = st.secrets["api_token"]

def cleanup_text(html_text):
    paragraphs = re.findall(r"<p>(.*?)</p>", html_text)
    if len(paragraphs) >= 2:
        body_content = " ".join(paragraphs[1:])
    else:
        body_content = html_text
    clean_text = re.sub(r"<[^>]+>", "", body_content)
    return clean_text.strip()

def get_description_from_web_url_bill(web_url):
    clean_url = str(web_url).strip().rstrip('/')
    parts = clean_url.split('/')
    try:
        idx = parts.index("bill")
        raw_congress = parts[idx + 1]
        raw_type = parts[idx + 2]
        bill_num = parts[idx + 3]
        congress_num = "".join(filter(str.isdigit, raw_congress))
    except (ValueError, IndexError):
        return "Error: Invalid Congress.gov bill web URL format."
    
    if raw_type == "house-bill":
        api_type = "hr"
    elif raw_type == "senate-bill":
        api_type = "s"
    else:
        api_type = raw_type.replace("-bill", "").replace("-", "").lower()

    api_url = f"https://api.congress.gov/v3/bill/{congress_num}/{api_type}/{bill_num}/summaries"
    params = {"api_key": token, "format": "json"}

    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        summaries_list = data.get("summaries", [])
        if summaries_list:
            return summaries_list[0].get("text", "No summary text found.")
        else:
            return "No summaries available for this bill yet."
    except requests.exceptions.RequestException as e:
        return f"API Request failed: {e}"
    
def get_description_from_web_url_amendment(web_url):
    clean_url = str(web_url).strip().rstrip('/')
    parts = clean_url.split('/')
    try:
        idx = parts.index("amendment")
        raw_congress = parts[idx + 1]
        raw_type = parts[idx + 2]
        amendment_num = parts[idx + 3]
        congress_num = "".join(filter(str.isdigit, raw_congress))
    except (ValueError, IndexError):
        return "Error: Invalid Congress.gov amendment web URL format."
    
    if raw_type == "house-amendment":
        api_type = "hamdt"
    elif raw_type == "senate-amendment":
        api_type = "samdt"
    else:
        api_type = f"{raw_type.lower()}amdt"

    api_url = f"https://api.congress.gov/v3/amendment/{congress_num}/{api_type}/{amendment_num}"
    params = {"api_key": token, "format": "json"}

    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("amendment", {}).get("description", "No description found.")
    except requests.exceptions.RequestException as e:
        return f"API Request failed: {e}"
    
def get_bill_name(type, congress, session, rollCallVoteNumber):
    base_url = "https://api.congress.gov/v3"
    url = f"{base_url}/{type}/{congress}/{session}/{rollCallVoteNumber}?format=json&api_key={token}"
    headers = {"Accept": "application/json"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"API Error: {e}", "Error fetching API data", ""

    vote_start = data.get('houseRollCallVote',{}).get('legislationType')
    vote_end = data.get('houseRollCallVote',{}).get('legislationNumber')
    
    if not vote_start or not vote_end:
        return "Unknown", "Could not isolate vote data structure", ""
        
    bill_number = vote_start + '.' + vote_end
    
    if 'amendmentNumber' in data.get('houseRollCallVote', {}):
        amendment_start = data.get('houseRollCallVote',{}).get('amendmentType')
        amendment_end = data.get('houseRollCallVote',{}).get('amendmentNumber')
        amendment_number = amendment_start + '.' + amendment_end
        full_bill_number = amendment_number + ' to ' + bill_number
        final_bill_number = re.sub(r"\bH(?=[A-Z])", "H.", full_bill_number)
        bill_url = data.get('houseRollCallVote',{}).get('legislationUrl')
        description = get_description_from_web_url_amendment(bill_url)
        return final_bill_number, description, bill_url
    
    elif bill_number:
        final_bill_number = re.sub(r"\bH(?=[A-Z])", "H.", bill_number)
        bill_url = data.get('houseRollCallVote',{}).get('legislationUrl')
        description = get_description_from_web_url_bill(bill_url)
        description_clean = cleanup_text(description)
        return final_bill_number, description_clean, bill_url
    
    else:
        return "Unknown", "Could not isolate vote data structure", ""

# --- NEW FUNCTION TO PARSE CONGRESS.GOV VOTE URLS ---
def parse_vote_url(url_string):
    """
    Parses a vote URL like: https://www.congress.gov/votes/house/118-2/513
    Returns: type, congress, session, rollCallVoteNumber
    """
    clean_url = str(url_string).strip().rstrip('/')
    parts = clean_url.split('/')
    try:
        idx = parts.index("votes")
        vote_type = parts[idx + 1] + "-vote"  # turns "house" into "house-vote"
        congress_session = parts[idx + 2]     # "118-2"
        vote_num = parts[idx + 3]             # "513"
        
        congress, session = congress_session.split('-')
        return vote_type, congress, session, vote_num
    except (ValueError, IndexError):
        return None

# --- STREAMLIT UI ---
st.title("Congress.gov Vote Parser")

# Step 1: File Uploader
uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])

if uploaded_file is not None:
    # Read CSV, skipping the first 3 rows as requested
    df = pd.read_csv(uploaded_file, skiprows=3)
    
    if "URL" not in df.columns:
        st.error("Error: The CSV does not contain a column named 'URL'.")
    else:
        st.write("Preview of uploaded data (first 5 rows):")
        st.dataframe(df.head())
        
        # Initialize session state to save processing time and prevent re-runs on download clicks
        if "processed_csv" not in st.session_state:
            st.session_state.processed_csv = None
            st.session_state.is_processed = False

        # Step 2: Trigger Processing via Button Click
        if st.button("Process URLs"):
            names = []
            descriptions = []
            urls = []
            
            progress_bar = st.progress(0)
            total_rows = len(df)
            
            for index, row in df.iterrows():
                url_val = row["URL"]
                parsed = parse_vote_url(url_val)
                
                if parsed:
                    v_type, v_congress, v_session, v_num = parsed
                    # Query API using extracted route variables
                    bill_name, bill_desc, api_bill_url = get_bill_name(v_type, v_congress, v_session, v_num)
                    
                    names.append(bill_name)
                    descriptions.append(bill_desc)
                    urls.append(api_bill_url)
                else:
                    names.append("Error")
                    descriptions.append("Invalid vote URL pattern found")
                    urls.append("")
                
                # Update visual loader tracking progress
                progress_bar.progress((index + 1) / total_rows)
            
            # Append generated values into columns appended to the right
            df["Name"] = names
            df["Description"] = descriptions
            df["URL_New"] = urls  # Named URL_New to distinguish from existing "URL" field
            
            # Store payload string directly inside context cache pipeline safely
            st.session_state.processed_csv = df.to_csv(index=False).encode('utf-8')
            st.session_state.is_processed = True
            st.success("Processing complete!")

        # Step 3: Present Download Element conditionally from saved memory instance
        if st.session_state.is_processed and st.session_state.processed_csv is not None:
            st.download_button(
                label="Download Processed CSV",
                data=st.session_state.processed_csv,
                file_name="processed_congress_votes.csv",
                mime="text/csv",
                key="download_button_instance" # Static key explicitly locks down accidental loop reruns
            )
