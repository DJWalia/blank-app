import io
import json
import os
from typing import Dict, List, Optional
import streamlit as st
import requests
import re
import pandas

# Load API credentials from Streamlit Secrets
token = st.secrets["api_token"]
uploaded_file = st.file_uploader("Upload your CSV spreadsheet file from congress.gov", type=["csv"])

def cleanup_text(html_text):
    """
    Cleans up HTML paragraph tags and removes extraneous tags from summary text blocks.
    """
    if not html_text:
        return ""
    paragraphs = re.findall(r"<p>(.*?)</p>", html_text)
    if len(paragraphs) >= 2:
        body_content = " ".join(paragraphs[1:])
    else:
        body_content = html_text
    clean_text = re.sub(r"<[^>]+>", "", body_content)
    return clean_text.strip()

def get_description_from_api_params(congress_num, api_type, bill_num):
    """
    Queries the official Congress.gov API summaries endpoint for standard bills.
    """
    api_url = f"https://congress.gov{congress_num}/{api_type}/{bill_num}/summaries"
    params = {"api_key": token, "format": "json"}
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        summaries_list = data.get("summaries", [])
        if summaries_list and isinstance(summaries_list, list):
            # Target the first summary text block safely
            return summaries_list[0].get("text", "No summary text found.")
        elif isinstance(summaries_list, dict):
            return summaries_list.get("text", "No summary text found.")
        return "No summaries available for this bill yet."
    except Exception as e:
        return f"API Request failed: {e}"

def get_amendment_description_from_api_params(congress_num, api_type, amendment_num):
    """
    Queries the official Congress.gov API description endpoint for direct amendments.
    """
    api_url = f"https://congress.gov{congress_num}/{api_type}/{amendment_num}"
    params = {"api_key": token, "format": "json"}
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("amendment", {}).get("description", "No description found.")
    except Exception as e:
        return f"API Request failed: {e}"

def get_bill_name_house(congress, session, rollCallVoteNumber):
    """
    Fetches details for House Roll Call Votes. Direct description parsing from 
    the 'voteDescription' or 'issue' fields resolves missing values for links like /votes/house/118-2/517.
    """
    base_url = "https://congress.gov"
    url = f"{base_url}/house-vote/{str(congress)}/{str(session)}/{str(rollCallVoteNumber)}?format=json&api_key={token}"
    headers = {"Accept": "application/json"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"House Vote #{rollCallVoteNumber}", f"API Error: {str(e)}", ""

    # Isolate core vote element
    vote_obj = data.get('houseRollCallVote', {})
    
    # Extract native text metadata safely embedded directly inside the roll call object
    vote_desc = vote_obj.get('voteDescription') or vote_obj.get('issue') or vote_obj.get('question', '')
    if not vote_desc:
        vote_desc = "House Roll Call Vote tracked from active tracking logs."
        
    vote_start = vote_obj.get('legislationType')
    vote_end = vote_obj.get('legislationNumber')
    
    # Rebuild clear user links matching standard conventions
    if vote_start and vote_end:
        bill_number = f"{vote_start}.{vote_end}"
        final_bill_number = re.sub(r"\bH(?=[A-Z])", "H.", bill_number)
        web_bill_type = "house-bill" if "H" in str(vote_start) else "senate-bill"
        rebuilt_web_url = f"https://congress.gov{congress}th-congress/{web_bill_type}/{vote_end}"
        return final_bill_number, cleanup_text(vote_desc), rebuilt_web_url
        
    elif 'amendmentNumber' in vote_obj:
        amendment_start = vote_obj.get('amendmentType')
        amendment_end = vote_obj.get('amendmentNumber')
        amendment_number = f"{amendment_start}.{amendment_end}"
        final_amend_number = re.sub(r"\bH(?=[A-Z])", "H.", amendment_number)
        web_amend_type = "house-amendment" if "H" in str(amendment_start) else "senate-amendment"
        rebuilt_web_url = f"https://congress.gov{congress}th-congress/{web_amend_type}/{amendment_end}"
        return final_amend_number, cleanup_text(vote_desc), rebuilt_web_url
        
    else:
        # Fallback return when no specific legislative number string matches
        fallback_url = f"https://www.congress.gov/votes/house/{congress}-{session}/{rollCallVoteNumber}"
        return f"House Vote #{rollCallVoteNumber}", cleanup_text(vote_desc), fallback_url

def get_bill_name_senate_direct(congress, bill_type, bill_number):
    """
    Handles straight bill page references passed directly from the spreadsheet layout rows.
    """
    if "house" in bill_type or bill_type == "hr":
        api_type = "hr"
        display_prefix = "H.R."
        web_type = "house-bill"
    else:
        api_type = "s"
        display_prefix = "S."
        web_type = "senate-bill"
    generated_web_url = f"https://congress.gov{congress}th-congress/{web_type}/{bill_number}"
    description = get_description_from_api_params(congress, api_type, bill_number)
    description_clean = cleanup_text(description)
    return f"{display_prefix} {bill_number}", description_clean, generated_web_url

def get_amendment_direct(congress, amend_type, amend_number):
    """
    Handles straight amendment page references passed directly from the spreadsheet layout rows.
    """
    if "house" in amend_type or amend_type == "hamdt":
        api_type = "hamdt"
        display_prefix = "H.Amdt."
        web_type = "house-amendment"
    else:
        api_type = "samdt"
        display_prefix = "S.Amdt."
        web_type = "senate-amendment"
    generated_web_url = f"https://congress.gov{congress}th-congress/{web_type}/{amend_number}"
    description = get_amendment_description_from_api_params(congress, api_type, amend_number)
    return f"{display_prefix} {amend_number}", description, generated_web_url

@st.cache_data(show_spinner=False)
def process_congress_csv(file_contents):
    """
    Cached background worker function processing parsing iterations safely without rerun triggers.
    """
    df = pandas.read_csv(io.BytesIO(file_contents), skiprows=3)
    if "URL" not in df.columns:
        return None, "Error: Could not find a 'URL' column. Check formatting."
        
    names, descriptions, urls = [], [], []
    for index, row in df.iterrows():
        url_val = str(row["URL"]).strip()
        # Normalizes prefix layouts by wiping out protocol domain heads
        url_val = re.sub(r'https?://(?:www\.)?congress\.gov/?', '', url_val)
        
        # Regex mappings tracking modern multi-branch routes cleanly
        match_vote = re.search(r'votes/house/(\d+)-(\d+)/(\d+)', url_val)
        match_bill = re.search(r'bill/(\d+)[a-z]*-congress/(house-bill|senate-bill|hr|s)/(\d+)', url_val)
        match_amend = re.search(r'amendment/(\d+)[a-z]*-congress/(house-amendment|senate-amendment|hamdt|samdt)/(\d+)', url_val)
        
        try:
            if match_vote:
                congress_str = match_vote.group(1)
                session_str = match_vote.group(2)
                vote_num = match_vote.group(3)
                name, desc, b_url = get_bill_name_house(congress_str, session_str, vote_num)
            elif match_bill:
                congress_str = match_bill.group(1)
                bill_type_str = match_bill.group(2)
                vote_num = match_bill.group(3)
                name, desc, b_url = get_bill_name_senate_direct(congress_str, bill_type_str, vote_num)
            elif match_amend:
                congress_str = match_amend.group(1)
                amend_type_str = match_amend.group(2)
                amend_num = match_amend.group(3)
                name, desc, b_url = get_amendment_direct(congress_str, amend_type_str, amend_num)
            else:
                name, desc, b_url = "N/A", "URL structure didn't match known House/Senate vote patterns", ""
        except Exception as e:
            name, desc, b_url = "Parsing Error", f"Exception: {str(e)}", ""
            
        names.append(name)
        descriptions.append(desc)
        urls.append(b_url)
        
    df["Name"] = names
    df["Description"] = descriptions
    df["URL_Generated"] = urls
    return df, "Success"

# Main visual setup presentation elements
if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    with st.spinner("Processing document data... (This runs once and will be cached)"):
        processed_df, status_msg = process_congress_csv(file_bytes)
        
    if processed_df is None:
        st.error(status_msg)
    else:
        st.success("Processing complete!")
        st.dataframe(processed_df.head())
        csv_buffer = io.StringIO()
        processed_df.to_csv(csv_buffer, index=False)
        csv_bytes = csv_buffer.getvalue().encode('utf-8')
        
        # Download handler executing seamlessly via the memory cache engine
        st.download_button(
            label="📥 Download Appended CSV Spreadsheet",
            data=csv_bytes,
            file_name="congress_votes_expanded.csv",
            mime="text/csv"
        )
