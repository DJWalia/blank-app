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
            if isinstance(summaries_list, list):
                return summaries_list[0].get("text", "No summary text found.")
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
    st.write(url)
    st.write(data)
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
    base_url = "https://api.congress.gov/v3/bill"
    url = f"{base_url}/{congress}/{bill_type}/{bill_number}/summaries?format=json&api_key={api_key}"
    headers = {"Accept": "application/json"}
    
    response = requests.get(url, headers=headers)
    data = response.json()
    st.write(data)
    return data.get("summaries", [])

def parse_vote_url(url_string):
    if pd.isna(url_string):
        return None
    clean_url = str(url_string).strip().rstrip('/')
    parts = clean_url.split('/')
    try:
        idx = parts.index("votes")
        vote_type = parts[idx + 1]
        if not vote_type.endswith("-vote"):
            vote_type = vote_type + "-vote"
        congress_session = parts[idx + 2]     
        vote_num = parts[idx + 3]             
        
        congress, session = congress_session.split('-')
        return vote_type, congress, session, vote_num
    except (ValueError, IndexError):
        return None

st.title("Congress.gov Legislative Record Vote Details (House)")

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
                parsed = parse_vote_url(url_val)
                
                if parsed:
                    v_type, v_congress, v_session, v_num = parsed
                    try:
                        bill_name, bill_desc, api_bill_url = get_bill_name(v_type, v_congress, v_session, v_num)
                        names.append(bill_name if bill_name else "")
                        descriptions.append(bill_desc if bill_desc else "")
                        urls.append(api_bill_url if api_bill_url else "")
                    except Exception:
                        names.append("")
                        descriptions.append("")
                        urls.append("")
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
            
            st.download_button(
                label="Download Processed CSV",
                data=st.session_state.processed_csv_bytes,
                file_name="processed_congress_votes.csv",
                mime="text/csv",
                key="download_button_instance"
            )

import datetime
import xml.etree.ElementTree as ET
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Vote Data Lookup", layout="wide")
st.title("CQ Vote Scorecard Details (Senate)")

def calculate_congress_session(year):
    if year < 1789:
        return None, None

    years_since_start = year - 1789
    congress_num = (years_since_start // 2) + 1
    session_num = 1 if (years_since_start % 2 == 0) else 2

    return congress_num, session_num


@st.cache_data(show_spinner=False)
def fetch_historical_metadata(year, vote_number):
    congress_num, session_num = calculate_congress_session(year)
    if not congress_num:
        return "N/A", "N/A", "Invalid Historical Year", "N/A"

    formatted_vote = str(vote_number).zfill(5)

    xml_url = f"https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress_num}{session_num}/vote_{congress_num}_{session_num}_{formatted_vote}.xml"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.get(xml_url, headers=headers, timeout=5)
        if (
            response.status_code != 200
            or b"<!DOCTYPE html" in response.content[:100]
        ):
            return "N/A", "N/A", f"Roll Call #{vote_number} Metadata", "N/A"

        root = ET.fromstring(response.content)
        v_date = (root.findtext("vote_date") or "N/A").strip()
        v_question = (root.findtext("vote_question") or "").strip()

        doc_node = root.find("document")
        amdt_node = root.find("amendment")
        nom_node = root.find("nomination")

        bill_id, bill_title = "N/A", v_question

        if doc_node is not None:
            bill_id = (doc_node.findtext("document_name") or "N/A").strip()
            bill_title = (doc_node.findtext("document_title") or v_question).strip()
        elif amdt_node is not None:
            bill_id = (
                amdt_node.findtext("amendment_number") or "Amendment"
            ).strip()
            bill_title = (
                amdt_node.findtext("statement_of_purpose") or v_question
            ).strip()
        elif nom_node is not None:
            bill_id = (
                nom_node.findtext("nomination_number") or "Nomination"
            ).strip()
            bill_title = (
                nom_node.findtext("nomination_description") or v_question
            ).strip()

        bill_link = "N/A"
        if bill_id != "N/A" and ("H.R." in bill_id or "S." in bill_id):
            clean_id = bill_id.replace(" ", "").replace(".", "").lower()
            type_slug = (
                "house-bill" if "hr" in clean_id else "senate-bill"
            )
            num_only = clean_id.replace("hr", "").replace("s", "")
            bill_link = f"https://congress.gov{congress_num}th-congress/{type_slug}/{num_only}"

        return bill_id, bill_link, bill_title, v_date
    except Exception:
        return "N/A", "N/A", f"Roll Call #{vote_number} ({year})", "N/A"

uploaded_file = st.file_uploader(
    "Upload CQ Vote Scorecard CSV", type=["csv"]
)

if uploaded_file is not None:
    raw_df = pd.read_csv(uploaded_file, header=None, keep_default_na=False)

    vote_numbers = [str(x).strip() for x in raw_df.iloc[0, 2:]]
    years_list = [int(x) for x in raw_df.iloc[1, 2:]]
    total_columns = len(vote_numbers)

    st.success(
        f"Detected **{total_columns}** vote columns."
    )

    batch_range = st.slider(
        "Select Column Range to Process",
        0,
        total_columns,
        (0, min(total_columns, total_columns)),
    )

    if st.button("Process CSV"):
        start_idx, end_idx = batch_range
        compiled_rows = []
        senator_rows = raw_df.iloc[2:]

        status_msg = st.empty()
        progress_bar = st.progress(0)

        sliced_votes = vote_numbers[start_idx:end_idx]
        sliced_years = years_list[start_idx:end_idx]
        workload = len(sliced_votes)

        for idx in range(workload):
            v_num = sliced_votes[idx]
            v_year = sliced_years[idx]
            
            actual_col_idx = 2 + start_idx + idx

            progress_bar.progress((idx + 1) / workload)
            status_msg.text(f"Processing {v_year} Roll Call #{v_num}... [Column {actual_col_idx}]")

            b_id, b_url, b_title, v_date = fetch_historical_metadata(v_year, v_num)
            c_num, s_num = calculate_congress_session(v_year)

            for _, row in senator_rows.iterrows():
                state_label = str(row[0]).strip()
                senator_name = str(row[1]).strip()
                
                vote_position = str(row[actual_col_idx]).strip()

                if not senator_name and not vote_position:
                    continue

                if (state_label == "" or state_label == "0") and compiled_rows:
                    state_label = compiled_rows[-1]["State"]

                compiled_rows.append({
                    "State": state_label,
                    "Senator": senator_name,
                    "Calendar Year": v_year,
                    "Congress Term": f"{c_num}th-{s_num}",
                    "Roll Call Vote": v_num,
                    "Specific Date": v_date,
                    "Measure ID": b_id,
                    "Congress.gov Link": b_url,
                    "Title / Summary": b_title,
                    "Position Cast": vote_position
                })

        tidy_df = pd.DataFrame(compiled_rows)
        
        tidy_df["State"] = tidy_df["State"].replace({"0": None, "": None}).ffill()
        tidy_df = tidy_df[tidy_df["Senator"] != "0"]

        status_msg.text("Processing complete!")

        final_csv = tidy_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Processed CSV",
            data=final_csv,
            file_name=f"historical_votes_{v_year}.csv",
            mime="text/csv",
        )
