import streamlit as st
import os, io, urllib.parse, time, pandas as pd, re
from datetime import datetime
from google import genai
from docx import Document
from fpdf import FPDF
from supabase import create_client, Client

# ---------------------------------------------------
# 0. UNIVERSAL UI LOCKDOWN
# ---------------------------------------------------
st.set_page_config(
    page_title="VakilDraft",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
    <style>
        #MainMenu {display:none !important;}
        footer {display:none !important;}
        header {visibility:hidden !important;}
        div[data-testid="stToolbar"] {visibility:hidden !important; height:0px !important;}
        .stAppDeployButton {display:none !important;}
        .block-container {padding-top:1rem !important;}
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------
# 1. SESSION STATE INIT
# ---------------------------------------------------
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.user_role = 'user'

if 'final_master' not in st.session_state:
    st.session_state.final_master = ""

if 'draft_history' not in st.session_state:
    st.session_state.draft_history = []

if 'facts_input' not in st.session_state:
    st.session_state.facts_input = ""

if 'selected_model' not in st.session_state:
    st.session_state.selected_model = "Auto-Pilot"

# Research states
if "search_links" not in st.session_state:
    st.session_state.search_links = []

if "selected_references" not in st.session_state:
    st.session_state.selected_references = []

# ---------------------------------------------------
# 2. LOGIN
# ---------------------------------------------------
if not st.session_state.authenticated:
    st.title("👨‍⚖️ VakilDraft Login")

    with st.form("login_form"):
        u = st.text_input("User")
        p = st.text_input("Password", type="password")

        if st.form_submit_button("Access"):
            creds = st.secrets.get("passwords", {})
            if u in creds and p == creds[u]:
                st.session_state.authenticated = True
                st.session_state.user_role = u.lower()
                st.rerun()
            else:
                st.error("Invalid credentials")

    st.stop()

# ---------------------------------------------------
# 3. STORAGE
# ---------------------------------------------------
SUPABASE_URL = "https://wuhsjcwtoradbzeqsoih.supabase.co"
SUPABASE_KEY = "sb_publishable_02nqexIYCCBaWryubZEkqA_Tw2PqX6m"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

VAULT_PATH = "private_vault"
if not os.path.exists(VAULT_PATH):
    os.makedirs(VAULT_PATH)

# ---------------------------------------------------
# 4. COURT DATA
# ---------------------------------------------------
COURT_DATA = {
    "High Court": ["Writ Petition (Civil)", "Writ Petition (Crl)", "Bail App", "Crl.MC", "Mat.Appeal", "RFA", "RSA"],
    "Family Court": ["OP (Divorce)", "MC (Maintenance)", "GOP (Guardianship)", "OP (Restitution)", "IA (Interim)"],
    "Munsiff Court": ["OS (Original Suit)", "EP (Execution Petition)", "RCP (Rent Control)", "CMA (Misc Appeal)"],
    "DVC (Domestic Violence)": ["DVA (Protection Order)", "Interim Maintenance", "Residence Order"],
    "MC (Magistrate)": ["CMP (Misc Petition)", "ST (Summary Trial)", "CC (Calendar Case)", "Bail Application"],
    "MVOP (Motor Accident)": ["OP (MV) Claim", "Ex-parte Set Aside", "Review Petition"]
}

DIST_SESSIONS_COURT = {
    "Civil": [
        "OS - Original Suit",
        "OP - Original Petition (Divorce / Family)",
        "EA - Execution Application / Petition",
        "MACT - Motor Accident Claim",
        "CMA - Civil Misc. Appeal",
        "Property/Title Dispute",
        "Contract Dispute",
        "Commercial/Company Suit"
    ],
    "Criminal": [
        "Sessions Case - Serious Offences",
        "CRR - Criminal Revision",
        "CRA - Criminal Appeal",
        "CMP - Criminal Misc. Petition",
        "Bail Application",
        "Contempt (Criminal)",
        "NDPS / Special Criminal Cases"
    ]
}

# ---------------------------------------------------
# 5. CORE FUNCTIONS
# ---------------------------------------------------
def perform_replacement(old, new):
    if new and old and "main_editor" in st.session_state:
        updated = st.session_state.main_editor.replace(old, new)
        st.session_state.final_master = updated
        st.session_state.main_editor = updated

def detect_unverified_citation(text):
    patterns = [
        r"\(\d{4}\)\s*\d+\s*SCC",
        r"AIR\s*\d{4}",
        r"\d{4}\s*KHC",
        r"\d{4}\s*Ker\s*LJ"
    ]
    for p in patterns:
        if re.search(p, text):
            return True
    return False

def smart_rotate_draft(prompt, facts, choice):
    projects = st.secrets.get("API_KEYS", [])
    effective_choice = choice if st.session_state.user_role == "admin" else "Auto-Pilot"

    target_model = (
        effective_choice
        if effective_choice != "Auto-Pilot"
        else ("gemini-2.5-pro" if len(facts) > 1200 else "gemini-2.5-flash")
    )

    start_time = time.time()

    for name, key in projects:
        try:
            client = genai.Client(api_key=key)
            res = client.models.generate_content(model=target_model, contents=prompt)
            return res.text, f"{name} ({target_model})", round(time.time() - start_time, 1)
        except:
            continue

    return None, "Offline", 0

def generate_search_keywords(dtype, facts):
    strict_prompt = f"""
Generate exactly 3 short legal issue-based search phrases.
STRICT RULES:
- Do NOT generate case names
- Do NOT generate citations
- Maximum 6 words per phrase
- Output only 3 lines

Petition Type: {dtype}
Facts: {facts}
"""
    result, _, _ = smart_rotate_draft(strict_prompt, facts, st.session_state.selected_model)
    if result:
        lines = [l.strip() for l in result.split("\n") if l.strip()]
        return lines[:3]
    return []

def generate_search_links(court, keywords):
    current_year = datetime.now().year
    years = f"{current_year} OR {current_year-1} OR {current_year-2}"
    domain = "highcourt.kerala.gov.in" if court == "High Court" else "sci.gov.in"
    links = []
    for phrase in keywords:
        query = f"site:{domain} {phrase} judgment ({years})"
        encoded = urllib.parse.quote_plus(query)
        links.append((phrase, f"https://www.google.com/search?q={encoded}"))
    return links

# ---------------------------------------------------
# 6. TOP BAR
# ---------------------------------------------------
col1, col2, col3 = st.columns([6, 2, 1])

with col1:
    st.markdown("## ⚖️ VakilDraft")

with col2:
    st.markdown(f"**Logged in as:** Adv. {st.session_state.user_role.upper()}")

with col3:
    if st.button("🚪 Logout"):
        st.session_state.authenticated = False
        st.session_state.user_role = "user"
        st.rerun()

st.divider()

# ---------------------------------------------------
# 7. COURT SELECTION
# ---------------------------------------------------
c1, c2 = st.columns(2)

with c1:
    court_options = [
        "High Court",
        "Dist & Sessions Court",
        "Family Court",
        "Munsiff Court",
        "DVC (Domestic Violence)",
        "MC (Magistrate)",
        "MVOP (Motor Accident)"
    ]

    court = st.selectbox("Court Level", court_options)

    if court == "Dist & Sessions Court":
        category = st.selectbox("Category", ["Civil", "Criminal"])
        case_types = DIST_SESSIONS_COURT.get(category, [])
        dtype = st.selectbox("Case Type", case_types)
    else:
        dtype = st.selectbox("Petition Type", COURT_DATA.get(court, []))

with c2:
    dists = [
        "Thiruvananthapuram","Kollam","Pathanamthitta","Alappuzha",
        "Kottayam","Idukki","Ernakulam","Thrissur","Palakkad",
        "Malappuram","Kozhikode","Wayanad","Kannur","Kasaragod"
    ]

    if court == "High Court":
        target_dist = "Ernakulam"
        st.text_input("District", value="Ernakulam (High Court of Kerala)", disabled=True)
    else:
        target_dist = st.selectbox("District", dists)

# ---------------------------------------------------
# 8. FACTS INPUT
# ---------------------------------------------------
st.session_state.facts_input = st.text_area(
    "Case Facts:",
    value=st.session_state.facts_input,
    height=150
)

# ---------------------------------------------------
# 8A. JUDGMENT RESEARCH
# ---------------------------------------------------
st.divider()
st.subheader("📚 Latest Judgments (Last 3 Years – Official Only)")

if st.button("🧠 Generate Judgment Search Links"):
    if st.session_state.facts_input.strip():
        keywords = generate_search_keywords(dtype, st.session_state.facts_input)
        st.session_state.search_links = generate_search_links(court, keywords)
    else:
        st.warning("Enter facts first.")

if st.session_state.search_links:
    selected_cases = []
    for i, (phrase, link) in enumerate(st.session_state.search_links):
        st.markdown(f"**Search Phrase:** {phrase}")
        st.markdown(f"[🔍 Search Official Website]({link})")
        citation = st.text_input("Paste Exact Case Title (Optional)", key=f"case_{i}")
        if citation.strip():
            selected_cases.append(citation.strip())
        st.markdown("---")
    st.session_state.selected_references = selected_cases

# ---------------------------------------------------
# 9. ACTION BUTTONS
# ---------------------------------------------------
b1, b2, b3 = st.columns(3)

with b1:
    if st.button("🚀 Draft Standard", type="primary", use_container_width=True):

        selected_meta = ""
        if st.session_state.selected_references:
            selected_meta = "\nRefer ONLY to the following judgments if relevant:\n"
            for ref in st.session_state.selected_references:
                selected_meta += f"{ref}\n"

        prompt = f"""
Draft {dtype} for {court} at {target_dist}.
Facts:
{st.session_state.facts_input}
{selected_meta}
STRICT RULES:
- STRICTLY use PARTY A and PARTY B
- Do NOT invent case law
- Do NOT fabricate citations
- If no references provided, do not include case law
"""

        with st.spinner("AI Drafting..."):
            res, tank, sec = smart_rotate_draft(prompt, st.session_state.facts_input, st.session_state.selected_model)

            if res:
                if detect_unverified_citation(res) and not st.session_state.selected_references:
                    st.error("Unverified citation detected. Draft blocked.")
                else:
                    st.session_state.final_master = res
                    st.session_state.draft_history.insert(
                        0,
                        {"label": f"{dtype} ({datetime.now().strftime('%H:%M')})", "content": res}
                    )
                    st.toast(f"Draft generated in {sec}s")

with b2:
    selected_ref = st.selectbox("Mirror Reference", ["None"] + os.listdir(VAULT_PATH))
    if st.button("✨ Mirror Style", use_container_width=True, disabled=(selected_ref == "None")):
        doc = Document(os.path.join(VAULT_PATH, selected_ref))
        dna = "\n".join([p.text for p in doc.paragraphs[:15]])
        prompt = f"Style DNA:\n{dna}\n\nDraft {dtype} for {court} at {target_dist}. Use PARTY A/B."
        with st.spinner("Mirroring..."):
            res, tank, sec = smart_rotate_draft(prompt, st.session_state.facts_input, st.session_state.selected_model)
            if res:
                st.session_state.final_master = res

with b3:
    if st.button("🗑️ Reset All", use_container_width=True):
        preserved_auth = st.session_state.get("authenticated", False)
        preserved_role = st.session_state.get("user_role", "user")
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.session_state.authenticated = preserved_auth
        st.session_state.user_role = preserved_role
        st.rerun()

# ---------------------------------------------------
# 10. STYLE VAULT
# ---------------------------------------------------
with st.expander("📁 Style Vault Upload"):
    uploaded = st.file_uploader("Upload Reference (.docx)", type="docx")
    if uploaded:
        with open(os.path.join(VAULT_PATH, uploaded.name), "wb") as f:
            f.write(uploaded.getbuffer())
        st.success("Uploaded successfully.")

# ---------------------------------------------------
# 11. DRAFT HISTORY
# ---------------------------------------------------
with st.expander("📜 Draft History (Last 10)"):
    for i, item in enumerate(st.session_state.draft_history[:10]):
        if st.button(item["label"], key=f"h_{i}"):
            st.session_state.final_master = item["content"]
            st.rerun()

# ---------------------------------------------------
# 12. EDITOR & DOWNLOAD
# ---------------------------------------------------
if st.session_state.final_master:

    st.divider()

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        p_a = st.text_input("Petitioner Name:", key="pet_name")
        st.button("Map 'PARTY A'", on_click=perform_replacement, args=("PARTY A", p_a), use_container_width=True)

    with col_b:
        p_b = st.text_input("Respondent Name:", key="res_name")
        st.button("Map 'PARTY B'", on_click=perform_replacement, args=("PARTY B", p_b), use_container_width=True)

    with col_c:
        f_old = st.text_input("Find:", key="f_txt")
        f_new = st.text_input("Replace:", key="r_txt")
        st.button("Replace All", on_click=perform_replacement, args=(f_old, f_new), use_container_width=True)

    st.text_area("Live Editor", value=st.session_state.final_master, height=500, key="main_editor")

    d1, d2 = st.columns(2)

    with d1:
        doc_gen = Document()
        doc_gen.add_paragraph(st.session_state.final_master)
        bio = io.BytesIO()
        doc_gen.save(bio)
        st.download_button("📥 MS Word", data=bio.getvalue(), file_name=f"{dtype}.docx")

    with d2:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=11)
        pdf.multi_cell(0, 10, st.session_state.final_master.encode('latin-1','replace').decode('latin-1'))
        st.download_button("📥 PDF", data=pdf.output(dest='S').encode('latin-1'), file_name=f"{dtype}.pdf")
