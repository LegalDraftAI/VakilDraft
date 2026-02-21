import streamlit as st
import os, io, urllib.parse, time, pandas as pd
from datetime import datetime
from google import genai
from docx import Document
from fpdf import FPDF
from supabase import create_client, Client

# --- 0. UNIVERSAL DEV UI LOCKDOWN (MUST BE FIRST STREAMLIT COMMAND) ---
st.set_page_config(
    page_title="Senior Advocate Workstation",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
    <style>
        /* Hide hamburger menu */
        #MainMenu {display: none !important;}

        /* Hide footer */
        footer {display: none !important;}

        /* Hide entire header (top-right icons area) */
        header {visibility: hidden !important;}

        /* Hide Streamlit toolbar (fullscreen, settings, etc.) */
        div[data-testid="stToolbar"] {
            visibility: hidden !important;
            height: 0px !important;
            position: fixed !important;
        }

        /* Hide Deploy button */
        .stAppDeployButton {
            display: none !important;
        }

        /* Remove extra top padding */
        .block-container {
            padding-top: 1rem !important;
        }
    </style>
""", unsafe_allow_html=True)

# --- 1. CONFIG & DEFAULT SESSION STATE ---
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

# --- 2. LOGIN ---
if not st.session_state.authenticated:
    st.title("👨‍⚖️ Workstation Login")
    with st.form("login"):
        u = st.text_input("User")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Access"):
            creds = st.secrets.get("passwords", {})
            if u in creds and p == creds[u]:
                st.session_state.authenticated = True
                st.session_state.user_role = u.lower()
                st.rerun()
    st.stop()

# --- 3. CLOUD & STORAGE ---
SUPABASE_URL = "https://wuhsjcwtoradbzeqsoih.supabase.co"
SUPABASE_KEY = "sb_publishable_02nqexIYCCBaWryubZEkqA_Tw2PqX6m"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

VAULT_PATH = "private_vault"
if not os.path.exists(VAULT_PATH):
    os.makedirs(VAULT_PATH)

# --- 4. COURT DATA ---
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

# --- 5. FUNCTIONS ---
def perform_replacement(old, new):
    if new and old and "main_editor" in st.session_state:
        updated_text = st.session_state.main_editor.replace(old, new)
        st.session_state.final_master = updated_text
        st.session_state.main_editor = updated_text

def smart_rotate_draft(prompt, facts, choice):
    projects = st.secrets.get("API_KEYS", [])
    effective_choice = choice if st.session_state.user_role == "admin" else "Auto-Pilot"
    target_model = effective_choice if effective_choice != "Auto-Pilot" else (
        "gemini-2.5-pro" if len(facts) > 1200 else "gemini-2.5-flash"
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

# --- 6. SIDEBAR ---
with st.sidebar:
    st.header(f"Adv. {st.session_state.user_role.upper()}")
    st.divider()

    st.subheader("📜 History (Last 10)")
    for i, item in enumerate(st.session_state.draft_history[:10]):
        if st.button(item["label"], key=f"h_{i}", use_container_width=True):
            st.session_state.final_master = item["content"]
            st.rerun()

    uploaded = st.file_uploader("Vault Reference (.docx)", type="docx")
    if uploaded:
        with open(os.path.join(VAULT_PATH, uploaded.name), "wb") as f:
            f.write(uploaded.getbuffer())

    selected_ref = st.selectbox("Mirror Logic:", ["None"] + os.listdir(VAULT_PATH))

# --- 7. MAIN INTERFACE ---
st.title("Legal Drafting Terminal")

_, top_right = st.columns([9, 1])
with top_right:
    if st.button("🚪 Sign Out"):
        st.session_state.authenticated = False
        st.session_state.user_role = "user"
        st.rerun()

c1, c2 = st.columns(2)

with c1:
    court = st.selectbox("Court Level", list(COURT_DATA.keys()) + ["Dist & Sessions Court"])
    if court == "Dist & Sessions Court":
        category = st.selectbox("Category", ["Civil", "Criminal"])
        case_types = DIST_SESSIONS_COURT.get(category, [])
        dtype = st.selectbox("Case Type", case_types)
    else:
        dtype = st.selectbox("Petition Type", COURT_DATA.get(court, []))

with c2:
    dists = ["Thiruvananthapuram", "Kollam", "Pathanamthitta", "Alappuzha",
             "Kottayam", "Idukki", "Ernakulam", "Thrissur", "Palakkad",
             "Malappuram", "Kozhikode", "Wayanad", "Kannur", "Kasaragod"]
    target_dist = "Ernakulam" if court == "High Court" else st.selectbox("District", dists)

st.session_state.facts_input = st.text_area(
    "Case Facts:",
    value=st.session_state.facts_input,
    height=150
)

if st.session_state.facts_input:
    search_q = urllib.parse.quote(f"{dtype} {st.session_state.facts_input[:50]} Kerala")
    with st.expander("🔍 Precedents & Indian Research", expanded=True):
        st.markdown(f"🔗 [Search Indian Kanoon](https://indiankanoon.org/search/?formInput={search_q})")

b1, b2, b3 = st.columns(3)

with b1:
    if st.button("🚀 Draft Standard", type="primary", use_container_width=True):
        p = f"Draft {dtype} for {court} at {target_dist}. Facts: {st.session_state.facts_input}. STRICTLY USE PARTY A/B. NO REAL NAMES."
        with st.spinner("AI Drafting..."):
            res, tank, sec = smart_rotate_draft(p, st.session_state.facts_input, st.session_state.selected_model)
            if res:
                st.session_state.final_master = res
                st.session_state.draft_history.insert(
                    0,
                    {"label": f"{dtype} ({datetime.now().strftime('%H:%M')})", "content": res}
                )
                st.toast(f"Done in {sec}s")

with b2:
    if st.button("✨ Mirror Style", use_container_width=True, disabled=(selected_ref == "None")):
        doc = Document(os.path.join(VAULT_PATH, selected_ref))
        dna = "\n".join([p.text for p in doc.paragraphs[:15]])
        p = f"Style DNA:\n{dna}\n\nDraft {dtype} for {st.session_state.facts_input}. Use PARTY A/B."
        with st.spinner("Mirroring..."):
            res, tank, sec = smart_rotate_draft(p, st.session_state.facts_input, st.session_state.selected_model)
            if res:
                st.session_state.final_master = res

with b3:
    if st.button("🗑️ Reset All", use_container_width=True):
        st.session_state.final_master = ""
        st.session_state.facts_input = ""
        st.rerun()

# --- EDITOR ---
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

    e1, e2, e3 = st.columns(3)

    with e2:
        doc_gen = Document()
        doc_gen.add_paragraph(st.session_state.final_master)
        bio = io.BytesIO()
        doc_gen.save(bio)
        st.download_button("📥 MS Word", data=bio.getvalue(), file_name=f"{dtype}.docx", use_container_width=True)

    with e3:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=11)
        pdf.multi_cell(0, 10, st.session_state.final_master.encode('latin-1', 'replace').decode('latin-1'))
        st.download_button("📥 PDF", data=pdf.output(dest='S').encode('latin-1'), file_name=f"{dtype}.pdf", use_container_width=True)

