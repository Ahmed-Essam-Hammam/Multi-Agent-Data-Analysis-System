import streamlit as st
import requests
import os
import re

# Configuration
API_URL = "http://localhost:8000"
CHARTS_DIR = "charts"

st.set_page_config(page_title="Multi-Source AI Agent", layout="wide")

st.title("📊 Multi-Source AI Agent")
st.markdown("Query your local data files and generate visualizations automatically.")

# --- Helper Function to Extract Chart Path ---
def extract_chart_path(text):
    """Extract chart file path from agent response."""
    # Try multiple patterns to catch different path formats
    patterns = [
        r"saved to:\s*(.+?\.png)",  # Matches: "saved to: C:\...\charts\file.png" or "saved to: charts/file.png"
        r"\[Chart saved to\s+(.+?\.png)\]",  # Matches: "[Chart saved to /path/to/chart.png]"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            full_path = match.group(1).strip()
            
            # If it's an absolute Windows or Unix path, extract just the relative part
            if "charts" in full_path.lower():
                # Extract everything from "charts" onwards
                # This handles: C:\Users\...\charts\file.png -> charts/file.png
                chart_match = re.search(r"charts[/\\]([\w\-_.]+\.png)", full_path, re.IGNORECASE)
                if chart_match:
                    return f"charts/{chart_match.group(1)}"
            
            # If it's already a relative path, return as-is
            if full_path.startswith("charts"):
                return full_path.replace("\\", "/")
            
            return full_path
    
    return None

# --- Initialization: Auto-Sync Files ---
if "current_files" not in st.session_state:
    try:
        response = requests.get(f"{API_URL}/files")
        if response.status_code == 200:
            st.session_state.current_files = response.json().get("files", [])
        else:
            st.session_state.current_files = []
    except:
        st.session_state.current_files = []

# --- Sidebar: File Management ---
with st.sidebar:
    st.header("📁 Data Management")
    
    # Refresh/Sync Button
    if st.button("🔄 Sync Folder"):
        response = requests.get(f"{API_URL}/files")
        if response.status_code == 200:
            st.session_state.current_files = response.json().get("files", [])
            st.success("Synced with uploads folder!")
    
    # Display List of Available Files
    if st.session_state.current_files:
        st.write("**Available Files:**")
        for f in st.session_state.current_files:
            st.caption(f"📄 {f}")
    else:
        st.info("No files found in uploads folder.")

    st.divider()

    # Upload New Files
    uploaded_files = st.file_uploader(
        "Upload New CSV or .db files", 
        type=["csv", "db"], 
        accept_multiple_files=True
    )
    
    if st.button("🚀 Upload & Process"):
        if uploaded_files:
            files_to_send = [("files", (f.name, f.getvalue())) for f in uploaded_files]
            response = requests.post(f"{API_URL}/upload", files=files_to_send)
            if response.status_code == 200:
                st.session_state.current_files = response.json().get("current_files")
                st.success("Files uploaded!")
            else:
                st.error("Upload failed.")

# --- Main Interface: Chat ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for idx, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
        # ONLY display chart if this message explicitly has chart_path stored AND it's not None
        if message["role"] == "assistant" and message.get("chart_path") is not None:
            if os.path.exists(message["chart_path"]):
                st.image(message["chart_path"], caption="Generated Visualization", width=500)
            else:
                st.caption(f"⚠️ Chart no longer exists: {message['chart_path']}")

# User Input
if prompt := st.chat_input("e.g., 'Show me a histogram of product prices'"):
    st.session_state.messages.append({"role": "user", "content": prompt, "chart_path": None})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call FastAPI Query Endpoint
    with st.chat_message("assistant"):
        with st.spinner("🤖 Analyzing data..."):
            try:
                response = requests.post(
                    f"{API_URL}/query", 
                    json={"prompt": prompt}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "No response.")
                    
                    # Display the text response
                    st.markdown(answer)
                    
                    # Extract and display chart if present
                    chart_path = extract_chart_path(answer)
                    
                    if chart_path and os.path.exists(chart_path):
                        st.image(chart_path, caption="Generated Visualization", width=500)
                        st.success(f"✅ Chart saved to: `{chart_path}`")
                        # Save message WITH the specific chart path
                        st.session_state.messages.append({
                            "role": "assistant", 
                            "content": answer,
                            "chart_path": chart_path  # Store ONLY this specific chart
                        })
                    else:
                        # No chart generated - explicitly set chart_path to None
                        st.session_state.messages.append({
                            "role": "assistant", 
                            "content": answer,
                            "chart_path": None  # Explicitly None so we know no chart exists
                        })
                        if chart_path:  # Path was found but file doesn't exist
                            st.warning(f"⚠️ Chart path found but file doesn't exist: {chart_path}")
                else:
                    error_msg = response.json().get('detail', 'Unknown error')
                    st.error(f"❌ Agent Error: {error_msg}")
                    
            except requests.exceptions.ConnectionError:
                st.error("🔌 Could not connect to backend. Make sure FastAPI is running on http://localhost:8000")
            except Exception as e:
                st.error(f"❌ Unexpected error: {e}")

# --- Footer with Chart Gallery ---
st.divider()

# Optional: Show all generated charts in a gallery
if st.checkbox("📸 Show Chart Gallery"):
    if os.path.exists(CHARTS_DIR):
        chart_files = [f for f in os.listdir(CHARTS_DIR) if f.endswith('.png')]
        if chart_files:
            st.subheader("Generated Charts")
            cols = st.columns(3)
            for idx, chart_file in enumerate(sorted(chart_files, reverse=True)):
                with cols[idx % 3]:
                    chart_path = os.path.join(CHARTS_DIR, chart_file)
                    st.image(chart_path, caption=chart_file, use_container_width=True)
        else:
            st.info("No charts generated yet.")
    else:
        st.info(f"Charts directory '{CHARTS_DIR}' not found.")