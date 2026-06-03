import io
import json
import os
from typing import Dict, List, Optional
import streamlit as st
import requests
import re
import pandas as pd

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
    st.write('hi')
    
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
    elif raw_type == "senate-resolution":
        api_type = "sres"
    elif raw_type == "senate-joint-resolution":
        api_type = "sjres"
    else:
        api_type = raw_type.replace("-bill", "").replace("-", "").lower()

    api_url = f"https://congress.gov/{congress_num}/{api_type}/{bill_num}/summaries"
    params = {"api_key": token, "format": "json"}

    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        
        data = response.json()
        summaries_list = data.get("summaries", [])
        
        if summaries_list:
            if isinstance(summaries_list, list):
                return summaries_list[0].get("text", "No summary text found.")
            return summaries_list.get("text", "No summary text found.")
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

    api_url = f"https://congress.gov/{congress_num}/{api_type}/{amendment_num}"
    params = {"api_key": token, "format": "json"}

    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        
        data = response.json()
        return data.get("amendment", {}).get("description", "No description found.")
        
    except requests.exceptions.RequestException as e:
        return f"API Request failed: {e}"
    
def get_bill_name(type, congress, session, rollCallVoteNumber):
    base_url = "https://congress.gov"
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

def get_bill_summary(congress, bill_type, bill_number, api_key):
    base_url = "https://congress.gov/bill"
    url = f"{base_url}/{congress}/{bill_type}/{bill_number}/summaries?format=json&api_key={api_key}"
    headers = {"Accept": "application/json"}
    
    response = requests.get(url, headers=headers)
    data = response.json()
    return data.get("summaries", [])

def format_senate_bill_name(url_string):
    clean_url = str(url_string).strip().rstrip('/')
    parts = clean_url.split('/')
    try:
        if "bill" in parts:
            idx = parts.index("bill")
        elif "amendment" in parts:
            idx = parts.index("amendment")
        else:
            return "Unknown"
        raw_type = parts[idx + 2]
        num = parts[idx + 3]
        if raw_type == "senate-bill":
            return f"S.{num}"
        elif raw_type == "senate-resolution":
            return f"S.Res.{num}"
        elif raw_type == "senate-amendment":
            return f"S.Amdt.{num}"
        elif raw_type == "senate-joint-resolution":
            return f"S.J.Res.{num}"
        return f"{raw_type}.{num}"
    except Exception:
        return "Unknown"

def process_universal_url(url_string):
    if pd.isna(url_string):
        return None
    
    clean_url = str(url_string).strip().rstrip('/')
    parts = clean_url.split('/')
    
    if "votes" in parts:
        try:
            idx = parts.index("votes")
            vote_type = parts[idx + 1]
            if not vote_type.endswith("-vote"):
                vote_type = vote_type + "-vote"
            congress_session = parts[idx + 2]     
            vote_num = parts[idx + 3]             
            congress, session = congress_session.split('-')
            
            bill_name, bill_desc, api_bill_url = get_bill_name(vote_type, congress, session, vote_num)
            return bill_name, bill_desc, api_bill_url
        except Exception:
            return "", "", ""
            
    elif "bill" in parts or "amendment" in parts:
        try:
            bill_name = format_senate_bill_name(url_string)
            if "amendment" in parts:
                bill_desc = get_description_from_web_url_amendment(url_string)
            else:
                raw_desc = get_description_from_web_url_bill(url_string)
                bill_desc = cleanup_text(raw_desc)
            return bill_name, bill_desc, url_string
        except Exception:
            return "", "", ""
            
    return "", "", ""

st.title("Congress.gov Legislative Parser")

if "current_file_name" not in st.session_state:
    st.session_state.current_file_name = None
    st.session_state.processed_df = None
    st.session_state.processed_csv_bytes = None

uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])

if uploaded_file is not None:
    if st.session_state.current_file_name != uploaded_file.name:
        st.session_state.current_file_name = uploaded_file.name
        st.session_state.processed_df = None
        st.session_state.processed_csv_bytes = None

    df = pd.read_csv(uploaded_file, skiprows=3)
    df = df.dropna(how="all")
    
    if "URL" not in df.columns:
        st.error("Error: The CSV does not contain a column named 'URL'.")
    else:
        if st.session_state.processed_df is None:
            names = []
            descriptions = []
            urls = []
            
            status_text = st.empty()
            progress_bar = st.progress(0)
            total_rows = len(df)
            
            for index, row in df.reset_index(drop=True).iterrows():
                status_text.text(f"Processing row {index + 1} of {total_rows}...")
                url_val = row["URL"]
                
                result = process_universal_url(url_val)
                if result:
                    b_name, b_desc, b_url = result
                    names.append(b_name if b_name else "")
                    descriptions.append(b_desc if b_desc else "")
                    urls.append(b_url if b_url else "")
                else:
                    names.append("")
                    descriptions.append("")
                    urls.append("")
                
                progress_bar.progress((index + 1) / total_rows)
            
            status_text.empty()
            progress_bar.empty()
            
            df["Name"] = names
            df["Bill Description"] = descriptions
            df["Bill URL"] = urls
            
            st.session_state.processed_df = df
            st.session_state.processed_csv_bytes = df.to_csv(index=False).encode('utf-8')
            st.success("Processing complete!")

        if st.session_state.processed_df is not None:
            st.write("### Processed Data Preview")
            st.dataframe(st.session_state.processed_df)
            
            st.download_button(
                label="Download Processed CSV",
                data=st.session_state.processed_csv_bytes,
                file_name="processed_congress_votes.csv",
                mime="text/csv",
                key="download_button_instance"
            )
