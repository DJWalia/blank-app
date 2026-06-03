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
        return f"Error: Invalid Congress.gov bill web URL format parsing target: {web_url}"
    
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
        
        if summaries_list and isinstance(summaries_list, list):
            # Target explicit first element block inside list
            return summaries_list[0].get("text", "No summary text found.")
        elif isinstance(summaries_list, dict):
            return summaries_list.get("text", "No summary text found.")
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
        return f"Error: Invalid Congress.gov amendment web URL format parsing target: {web_url}"
    
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
    
def get_bill_name_house(type, congress, session, rollCallVoteNumber):
    base_url = "https://congress.gov"
    url = f"{base_url}/house-vote/{str(congress)}/{str(session)}/{str(rollCallVoteNumber)}?format=json&api_key={token}"
    
    headers = {"Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"House Vote #{rollCallVoteNumber}", f"API Error: Failed fetching metadata: {str(e)}", ""

    vote_start = data.get('houseRollCallVote', {}).get('legislationType')
    vote_end = data.get('houseRollCallVote', {}).get('legislationNumber')
    
    if not vote_start or not vote_end:
        return f"House Vote #{rollCallVoteNumber}", "Could not isolate metadata structure inside API.", ""

    bill_number = f"{vote_start}.{vote_end}"
    
    # Fix: Reconstruct actual Web URLs instead of sending the internal API strings down to parser
    if 'amendmentNumber' in data.get('houseRollCallVote', {}):
        amendment_start = data.get('houseRollCallVote', {}).get('amendmentType')
        amendment_end = data.get('houseRollCallVote', {}).get('amendmentNumber')
        amendment_number = f"{amendment_start}.{amendment_end}"
        full_bill_number = f"{amendment_number} to {bill_number}"
        final_bill_number = re.sub(r"\bH(?=[A-Z])", "H.", full_bill_number)
        
        # Build direct clean consumer web target url
        web_amend_type = "house-amendment" if "H" in str(amendment_start) else "senate-amendment"
        rebuilt_web_url = f"https://www.congress.gov/amendment/{congress}th-congress/{web_amend_type}/{amendment_end}"
        description = get_description_from_web_url_amendment(rebuilt_web_url)
        return final_bill_number, description, rebuilt_web_url
    
    elif bill_number:
        final_bill_number = re.sub(r"\bH(?=[A-Z])", "H.", bill_number)
        web_bill_type = "house-bill" if "H" in str(vote_start) else "senate-bill"
        rebuilt_web_url = f"https://congress.gov{congress}th-congress/{web_bill_type}/{vote_end}"
        description = get_description_from_web_url_bill(rebuilt_web_url)
        description_clean = cleanup_text(description)
        return final_bill_number, description_clean, rebuilt_web_url
    else:
        return f"House Vote #{rollCallVoteNumber}", "Could not isolate target bill components.", ""

def get_bill_name_senate_direct(congress, bill_type, bill_number):
    if "house" in bill_type:
        api_type = "hr"
        display_prefix = "H.R."
    elif "senate" in bill_type:
        api_type = "s"
        display_prefix = "S."
    else:
        api_type = "s"
        display_prefix = "S."

    generated_web_url = f"https://congress.gov{congress}th-congress/{bill_type}/{bill_number}"
    description = get_description_from_web_url_bill(generated_web_url)
    description_clean = cleanup_text(description)
    
    return f"{display_prefix} {bill_number}", description_clean, generated_web_url

def get_amendment_direct(congress, amend_type, amend_number):
    if "house" in amend_type:
        display_prefix = "H.Amdt."
    elif "senate" in amend_type:
        display_prefix = "S.Amdt."
    else:
        display_prefix = "S.Amdt."

    generated_web_url = f"https://www.congress.gov/amendment/{congress}th-congress/{amend_type}/{amend_number}"
    description = get_description_from_web_url_amendment(generated_web_url)
    
    return f"{display_prefix} {amend_number}", description, generated_web_url

# Cache data engine step logic
@st.cache_data(show_spinner=False)
def process_congress_csv(file_contents):
    df = pandas.read_csv(io.BytesIO(file_contents), skiprows=3)
    
    if "URL" not in df.columns:
        return None, "Error: Could not find a 'URL' column. Check formatting."
        
    names, descriptions, urls = [], [], []
    
    for index, row in df.iterrows():
        url_val = str(row["URL"]).strip()
        parts = url_val.split('/')
        
        try:
            # Route 1: Modern pattern: /votes/house/118-2/517
            if "votes" in parts and "house" in parts:
                idx = parts.index("house")
                hyphen_mix = parts[idx+1]
                
                if "-" in hyphen_mix:
                    congress_str, session_str = hyphen_mix.split('-')
                else:
                    congress_str = "".join(filter(str.isdigit, hyphen_mix))
                    session_str = "1"
                    
                # Fix: Extract raw string out of array layout wrapper using [0]
                vote_num = parts[idx+2].split('?')[0]
                name, desc, b_url = get_bill_name_house("house-vote", congress_str, session_str, vote_num)
                
            # Route 2: Base layout bill paths: /bill/119th-congress/senate-bill/4664
            elif "bill" in parts:
                idx = parts.index("bill")
                congress_str = "".join(filter(str.isdigit, parts[idx+1]))
                bill_type_str = parts[idx+2]
                vote_num = parts[idx+3].split('?')[0]
                
                name, desc, b_url = get_bill_name_senate_direct(congress_str, bill_type_str, vote_num)
                
            # Route 3: Amendment path processing: /amendment/119th-congress/senate-amendment/5350
            elif "amendment" in parts:
                idx = parts.index("amendment")
                congress_str = "".join(filter(str.isdigit, parts[idx+1]))
                amend_type_str = parts[idx+2]
                amend_num = parts[idx+3].split('?')[0]
                
                name, desc, b_url = get_amendment_direct(congress_str, amend_type_str, amend_num)
                
            else:
                name, desc, b_url = "N/A", "URL format not matching criteria", ""
                
        except Exception as e:
            name, desc, b_url = "Parsing Error", f"Exception: {str(e)}", ""
            
        names.append(name)
        descriptions.append(desc)
        urls.append(b_url)
        
    df["Name"] = names
    df["Description"] = descriptions
    df["URL_Generated"] = urls
    return df, "Success"

# Presentation Execution Loop Step
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
        st.download_button(label="📥 Download Appended CSV Spreadsheet",data=csv_bytes,file_name="congress_votes_expanded.csv",mime="text/csv")
