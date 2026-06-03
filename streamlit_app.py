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
    
    if raw_type == "house-bill":
        api_type = "hr"
    elif raw_type == "senate-bill":
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
    base_url = "https://api.congress.gov/v3"
    url = f"{base_url}/{type}/{congress}/{session}/{rollCallVoteNumber}?format=json&api_key={token}"
    
    headers = {"Accept": "application/json"}

    response = requests.get(url, headers=headers)
    data = response.json()

    vote_start = data.get('houseRollCallVote',{}).get('legislationType')
    vote_end = data.get('houseRollCallVote',{}).get('legislationNumber')
    
    if not vote_start or not vote_end:
        return "Unknown", "Could not isolate metadata from House API.", ""

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
        return "Unknown", "Could not isolate the vote object.", ""

def get_bill_name_senate(type, congress, session, rollCallVoteNumber):
    
    base_url = f"https://senate.gov{congress}&session={session}&vote={rollCallVoteNumber.zfill(5)}"
    
    return f"Senate Vote #{rollCallVoteNumber}", "Senate Roll Call Vote data pulled from record summary reference.", base_url

if uploaded_file is not None:
    df = pandas.read_csv(uploaded_file, skiprows=3)
    
    if "URL" not in df.columns:
        st.error("Error: Could not find a 'URL' column in the uploaded spreadsheet.")
    else:
        names = []
        descriptions = []
        urls = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_rows = len(df)
        
        for index, row in df.iterrows():
            url_val = str(row["URL"]).strip()
            
            status_text.text(f"Processing row {index + 1} of {total_rows}...")
            progress_bar.progress((index + 1) / total_rows)
            
            parts = url_val.split('/')
            
            try:
                if "house-vote" in parts:
                    idx = parts.index("house-vote")
                    congress_str = "".join(filter(str.isdigit, parts[idx+1]))
                    session_str = "".join(filter(str.isdigit, parts[idx+2]))
                    vote_num = parts[idx+3].split('?')[0]
                    
                    name, desc, b_url = get_bill_name_house("house-vote", congress_str, session_str, vote_num)
                    
                elif "senate-vote" in parts:
                    idx = parts.index("senate-vote")
                    congress_str = "".join(filter(str.isdigit, parts[idx+1]))
                    session_str = "".join(filter(str.isdigit, parts[idx+2]))
                    vote_num = parts[idx+3].split('?')[0]
                    
                    name, desc, b_url = get_bill_name_senate("senate-vote", congress_str, session_str, vote_num)
                    
                else:
                    name, desc, b_url = "N/A", "Not a valid Congress Roll Call URL format", ""
                    
            except Exception as e:
                name, desc, b_url = "Error", f"Parsing error occurred: {str(e)}", ""
                
            names.append(name)
            descriptions.append(desc)
            urls.append(b_url)
            
        df["Name"] = names
        df["Description"] = descriptions
        df["URL_Generated"] = urls 
        
        status_text.text("Processing complete!")
        st.dataframe(df.head())
        
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_bytes = csv_buffer.getvalue().encode('utf-8')
        
        st.download_button(
            label="📥 Download Appended CSV Spreadsheet",
            data=csv_bytes,
            file_name="congress_votes_expanded.csv",
            mime="text/csv"
        )
