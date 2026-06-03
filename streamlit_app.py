import io
import json
import os
from typing import Dict, List, Optional
import streamlit as st
import requests
import re
import pandas

token = st.secrets["api_token"]
uploaded_file = st.file_uploader("Upload your CSV spreadsheet file from congress.gov", type=["csv"])

def cleanup_text(html_text):
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
    api_url = f"https://api.congress.gov/v3/bill/{congress_num}/{api_type}/{bill_num}/summaries"
    params = {"api_key": token, "format": "json"}
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        summaries_list = data.get("summaries", [])
        if summaries_list and isinstance(summaries_list, list):
            return summaries_list[0].get("text", "No summary text found.")
        elif isinstance(summaries_list, dict):
            return summaries_list.get("text", "No summary text found.")
        return "No summaries available for this bill yet."
    except Exception as e:
        return f"API Request failed: {e}"

def get_amendment_description_from_api_params(congress_num, api_type, amendment_num):
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
    base_url = "https://api.congress.gov/v3"
    url = f"{base_url}/house-vote/{str(congress)}/{str(session)}/{str(rollCallVoteNumber)}?format=json&api_key={token}"
    headers = {"Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"House Vote #{rollCallVoteNumber}", f"API Error: {str(e)}", ""

    vote_start = data.get('houseRollCallVote', {}).get('legislationType')
    vote_end = data.get('houseRollCallVote', {}).get('legislationNumber')
    if not vote_start or not vote_end:
        return f"House Vote #{rollCallVoteNumber}", "Could not isolate metadata structure inside API.", ""

    bill_number = f"{vote_start}.{vote_end}"
    if 'amendmentNumber' in data.get('houseRollCallVote', {}):
        amendment_start = data.get('houseRollCallVote', {}).get('amendmentType')
        amendment_end = data.get('houseRollCallVote', {}).get('amendmentNumber')
        amendment_number = f"{amendment_start}.{amendment_end}"
        full_bill_number = f"{amendment_number} to {bill_number}"
        final_bill_number = re.sub(r"\bH(?=[A-Z])", "H.", full_bill_number)
        
        api_amend_type = "hamdt" if "H" in str(amendment_start) else "samdt"
        web_amend_type = "house-amendment" if "H" in str(amendment_start) else "senate-amendment"
        rebuilt_web_url = f"https://congress.gov{congress}th-congress/{web_amend_type}/{amendment_end}"
        description = get_amendment_description_from_api_params(congress, api_amend_type, amendment_end)
        return final_bill_number, description, rebuilt_web_url
    elif bill_number:
        final_bill_number = re.sub(r"\bH(?=[A-Z])", "H.", bill_number)
        api_bill_type = "hr" if "H" in str(vote_start) else "s"
        web_bill_type = "house-bill" if "H" in str(vote_start) else "senate-bill"
        rebuilt_web_url = f"https://www.congress.gov/bill/{congress}th-congress/{web_bill_type}/{vote_end}"
        description = get_description_from_api_params(congress, api_bill_type, vote_end)
        description_clean = cleanup_text(description)
        return final_bill_number, description_clean, rebuilt_web_url
    return f"House Vote #{rollCallVoteNumber}", "Could not isolate target bill components.", ""

def get_bill_name_senate_direct(congress, bill_type, bill_number):
    if "house" in bill_type or bill_type == "hr":
        api_type = "hr"
        display_prefix = "H.R."
        web_type = "house-bill"
    else:
        api_type = "s"
        display_prefix = "S."
        web_type = "senate-bill"
    generated_web_url = f"https://www.congress.gov/bill/{congress}th-congress/{web_type}/{bill_number}"
    description = get_description_from_api_params(congress, api_type, bill_number)
    description_clean = cleanup_text(description)
    return f"{display_prefix} {bill_number}", description_clean, generated_web_url

def get_amendment_direct(congress, amend_type, amend_number):
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
    df = pandas.read_csv(io.BytesIO(file_contents), skiprows=3)
    if "URL" not in df.columns:
        return None, "Error: Could not find a 'URL' column. Check formatting."
        
    names, descriptions, urls = [], [], []
    for index, row in df.iterrows():
        url_val = str(row["URL"]).strip()
        url_val = re.sub(r'https?://(?:www\.)?congress\.gov/?', '', url_val)
        
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
        
        st.download_button(
            label="📥 Download Appended CSV Spreadsheet",
            data=csv_bytes,
            file_name="congress_votes_expanded.csv",
            mime="text/csv"
        )
