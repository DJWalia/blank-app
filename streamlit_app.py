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
    
    if raw_type in ["house-bill", "hr"]:
        api_type = "hr"
    elif raw_type in ["senate-bill", "s"]:
        api_type = "s"
    else:
        api_type = raw_type.replace("-bill", "").replace("-", "").lower()

    api_url = f"https://congress.gov{congress_num}/{api_type}/{bill_num}/summaries"
    params = {"api_key": token, "format": "json"}

    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        summaries_list = data.get("summaries", [])
        if summaries_list and isinstance(summaries_list, list) and len(summaries_list) > 0:
            return summaries_list[0].get("text", "No summary text found.")
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
    
    if raw_type in ["house-amendment", "hamdt"]:
        api_type = "hamdt"
    elif raw_type in ["senate-amendment", "samdt"]:
        api_type = "samdt"
    else:
        api_type = f"{raw_type.lower()}amdt"

    api_url = f"https://congress.gov{congress_num}/{api_type}/{amendment_num}"
    params = {"api_key": token, "format": "json"}

    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("amendment", {}).get("description", "No description found.")
    except requests.exceptions.RequestException as e:
        return f"API Request failed: {e}"
    
def get_bill_title_direct(congress, api_type, bill_number):
    api_url = f"https://congress.gov{str(congress)}/{str(api_type)}/{str(bill_number)}"
    params = {"api_key": token, "format": "json"}
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("bill", {}).get("title", f"Bill {str(bill_number).upper()}")
    except Exception:
        return f"Bill {str(bill_number).upper()}"

def get_bill_name(type, congress, session, rollCallVoteNumber):
    base_url = "https://congress.gov"
    url = f"{base_url}/{type}/{congress}/{session}/{rollCallVoteNumber}?format=json&api_key={token}"
    headers = {"Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"House Vote #{rollCallVoteNumber}", f"API Request failed: {str(e)}", ""

    vote_obj = data.get('houseRollCallVote', {})
    vote_start = vote_obj.get('legislationType')
    vote_end = vote_obj.get('legislationNumber')
    leg_url = vote_obj.get('legislationUrl', '')
    
    if leg_url:
        parts = [p for p in leg_url.split('/') if p]
        if "bill" in parts:
            idx = parts.index("bill")
            try:
                target_congress = parts[idx+1]
                target_api_type = parts[idx+2].lower()
                target_bill_num = parts[idx+3].split('?')[0]
                if target_api_type == "hr":
                    web_bill_type = "house-bill"
                elif target_api_type == "s":
                    web_bill_type = "senate-bill"
                else:
                    web_bill_type = f"{target_api_type}-bill"
                bill_title = get_bill_title_direct(target_congress, target_api_type, target_bill_num)
                description = get_description_from_web_url_bill(leg_url)
                rebuilt_web_url = f"https://congress.gov{target_congress}th-congress/{web_bill_type}/{target_bill_num}"
                return bill_title, cleanup_text(description), rebuilt_web_url
            except Exception:
                pass

    bill_number = None
    if vote_start and vote_end:
        bill_number = vote_start + '.' + vote_end
    
    if 'amendmentNumber' in vote_obj:
        amendment_start = vote_obj.get('amendmentType')
        amendment_end = vote_obj.get('amendmentNumber')
        amendment_number = amendment_start + '.' + amendment_end
        full_bill_number = amendment_number + ' to ' + (bill_number if bill_number else "")
        final_bill_number = re.sub(r"\bH(?=[A-Z])", "H.", full_bill_number)
        bill_url = vote_obj.get('legislationUrl')
        description = get_description_from_web_url_amendment(bill_url)
        return final_bill_number, description, bill_url
    elif bill_number:
        final_bill_number = re.sub(r"\bH(?=[A-Z])", "H.", bill_number)
        bill_url = vote_obj.get('legislationUrl')
        description = get_description_from_web_url_bill(bill_url)
        description_clean = cleanup_text(description)
        return final_bill_number, description_clean, bill_url
    else:
        return f"House Vote #{rollCallVoteNumber}", "Could not isolate target bill structures.", ""

def get_bill_name_senate_direct(congress, bill_type, bill_number):
    bill_type_clean = str(bill_type).lower()
    if bill_type_clean in ["house-bill", "hr"]:
        api_type = "hr"
        web_type = "house-bill"
    else:
        api_type = "s"
        web_type = "senate-bill"
    generated_web_url = f"https://congress.gov{str(congress)}th-congress/{web_type}/{str(bill_number)}"
    bill_title = get_bill_title_direct(congress, api_type, bill_number)
    description = get_description_from_web_url_bill(generated_web_url)
    description_clean = cleanup_text(description)
    return bill_title, description_clean, generated_web_url

def get_amendment_direct(congress, amend_type, amend_number):
    amend_type_clean = str(amend_type).lower()
    if amend_type_clean in ["house-amendment", "hamdt"]:
        api_type = "hamdt"
        web_type = "house-amendment"
    else:
        api_type = "samdt"
        web_type = "senate-amendment"
    generated_web_url = f"https://congress.gov{str(congress)}th-congress/{web_type}/{str(amend_number)}"
    description = get_amendment_description_from_web_url_amendment(generated_web_url)
    return f"Amendment #{amend_number}", description, generated_web_url

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
                vote_num_str = match_vote.group(3).split('?')[0]
                name, desc, b_url = get_bill_name("house-vote", congress_str, session_str, vote_num_str)
            elif match_bill:
                congress_str = match_bill.group(1)
                bill_type_str = match_bill.group(2)
                vote_num_str = match_bill.group(3).split('?')[0]
                name, desc, b_url = get_bill_name_senate_direct(congress_str, bill_type_str, vote_num_str)
            elif match_amend:
                congress_str = match_amend.group(1)
                amend_type_str = match_amend.group(2)
                amend_num_str = match_amend.group(3).split('?')[0]
                name, desc, b_url = get_amendment_direct(congress_str, amend_type_str, amend_num_str)
            else:
                name, desc, b_url = "N/A", "URL format not matching criteria", ""
        except Exception as e:
            name, desc, b_url = "Parsing Error", f"Exception: {str(e)}", ""
        names.append(name)
        descriptions.append(desc)
        urls.append(b_url)
    df["Name"] = names
    df["Description"] = descriptions
    if "URL" in df.columns:
        df = df.drop(columns=["URL"])
    df["URL"] = urls
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
