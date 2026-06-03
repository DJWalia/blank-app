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
        
        # 4. Extract digits to get "118"
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
    st.write('hi, this is an amendment')
    
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

    response = requests.get(url, headers=headers)
    data = response.json()

    vote_start = data.get('houseRollCallVote',{}).get('legislationType')
    vote_end = data.get('houseRollCallVote',{}).get('legislationNumber')
    bill_number = vote_start+'.'+vote_end
    
    if 'amendmentNumber' in data.get('houseRollCallVote', {}):
        amendment_start = data.get('houseRollCallVote',{}).get('amendmentType')
        amendment_end = data.get('houseRollCallVote',{}).get('amendmentNumber')
        amendment_number = amendment_start+'.'+amendment_end
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
        st.write("Could not isolate the vote object. Raw JSON structure:")
        st.write(data)


