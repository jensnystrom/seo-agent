"""
Villalife SEO Dashboard — Streamlit
Kör lokalt: streamlit run dashboard.py
"""

import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread
from dotenv import load_dotenv

load_dotenv()

# ── Konfiguration ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Villalife SEO Dashboard",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_FILE = os.getenv("GSC_SERVICE_ACCOUNT_FILE")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Styling ──────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: #1c1f26;
        border-radius: 12px;
        padding: 20px 24px;
        border: 1px solid #2d3139;
    }
    .metric-value { font-size: 2.2rem; font-weight: 700; color: #ffffff; }
    .metric-label { font-size: 0.85rem; color: #8b8fa8; margin-bottom: 4px; }
    .metric-delta-up { color: #4ade80; font-size: 0.85rem; }
    .metric-delta-down { color: #f87171; font-size: 0.85rem; }
    .status-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-published { background: #14532d; color: #4ade80; }
    .badge-waiting { background: #1e3a5f; color: #60a5fa; }
    .badge-quick-win { background: #3b1f6b; color: #c084fc; }
    .badge-gap { background: #1e3a5f; color: #60a5fa; }
    h1 { font-size: 1.6rem !important; }
    .stTabs [data-baseweb="tab"] { font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)


# ── Data-hämtning ─────────────────────────────────────────────────────────────

def get_credentials():
    """Hämtar Google-credentials från Streamlit secrets eller lokal fil."""
    try:
        # Streamlit Cloud: credentials lagrade som secrets
        info = {
            "type": st.secrets["gcp"]["type"],
            "project_id": st.secrets["gcp"]["project_id"],
            "private_key_id": st.secrets["gcp"]["private_key_id"],
            "private_key": st.secrets["gcp"]["private_key"],
            "client_email": st.secrets["gcp"]["client_email"],
            "client_id": st.secrets["gcp"]["client_id"],
            "auth_uri": st.secrets["gcp"]["auth_uri"],
            "token_uri": st.secrets["gcp"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["gcp"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["gcp"]["client_x509_cert_url"],
            "universe_domain": "googleapis.com",
        }
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    except (KeyError, FileNotFoundError):
        # Lokal utveckling: läs från fil
        return Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)


@st.cache_data(ttl=300)  # Cache 5 min
def load_sheet_data():
    try:
        sheet_id = SHEET_ID or st.secrets.get("GOOGLE_SHEET_ID", "")
        creds = get_credentials()
        client = gspread.authorize(creds)
        sh = client.open_by_key(sheet_id)

        data = {}
        for ws in sh.worksheets():
            rows = ws.get_all_records()
            data[ws.title] = pd.DataFrame(rows) if rows else pd.DataFrame()
        return data, None
    except Exception as e:
        return {}, str(e)


# ── Header ────────────────────────────────────────────────────────────────────

col_title, col_refresh = st.columns([6, 1])
with col_title:
    st.markdown("## 🏠 Villalife SEO Dashboard")
    st.caption(f"Senast uppdaterad: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
with col_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("↻ Uppdatera", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ── Ladda data ────────────────────────────────────────────────────────────────

data, error = load_sheet_data()

if error:
    st.error(f"Kunde inte ansluta till Google Sheets: {error}")
    st.stop()

gsc_df = data.get("📈 GSC Data", pd.DataFrame())
pipeline_df = data.get("✍️ Content Pipeline", pd.DataFrame())
queue_df = data.get("🎯 Optimeringsköen", pd.DataFrame())
log_df = data.get("📋 Aktivitetslogg", pd.DataFrame())

# ── KPI-kort ──────────────────────────────────────────────────────────────────

latest_clicks = int(gsc_df["Klick"].iloc[-1]) if not gsc_df.empty and "Klick" in gsc_df else 0
prev_clicks = int(gsc_df["Klick"].iloc[-2]) if len(gsc_df) > 1 and "Klick" in gsc_df else 0
latest_imp = int(gsc_df["Visningar"].iloc[-1]) if not gsc_df.empty and "Visningar" in gsc_df else 0
latest_pos = float(gsc_df["Snitt Position"].iloc[-1]) if not gsc_df.empty and "Snitt Position" in gsc_df else 0

click_delta = latest_clicks - prev_clicks
click_pct = round((click_delta / prev_clicks * 100), 1) if prev_clicks > 0 else 0

published_total = len(pipeline_df) if not pipeline_df.empty else 0
queue_pending = len(queue_df[queue_df["Status"] == "Väntar"]) if not queue_df.empty and "Status" in queue_df else 0
log_today = len(log_df[log_df["Tidpunkt"].str.startswith(datetime.now().strftime("%Y-%m-%d"))]) if not log_df.empty and "Tidpunkt" in log_df else 0

k1, k2, k3, k4, k5 = st.columns(5)

def kpi(col, label, value, delta=None, delta_suffix=""):
    delta_html = ""
    if delta is not None:
        sign = "+" if delta >= 0 else ""
        color = "metric-delta-up" if delta >= 0 else "metric-delta-down"
        arrow = "▲" if delta >= 0 else "▼"
        delta_html = f'<div class="{color}">{arrow} {sign}{delta}{delta_suffix}</div>'
    col.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value">{value}</div>
      {delta_html}
    </div>
    """, unsafe_allow_html=True)

kpi(k1, "Klick (senaste period)", latest_clicks, click_delta, f" ({click_pct}%)")
kpi(k2, "Visningar", f"{latest_imp:,}".replace(",", " "))
kpi(k3, "Snittposition", latest_pos)
kpi(k4, "Publicerade artiklar", published_total)
kpi(k5, "I kön (Väntar)", queue_pending)

st.markdown("<br>", unsafe_allow_html=True)

# ── Flikar ────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs(["📈 Trafik", "✍️ Content Pipeline", "🎯 Optimeringskön", "📋 Aktivitetslogg"])

# ── TAB 1: Trafik ─────────────────────────────────────────────────────────────

with tab1:
    if gsc_df.empty:
        st.info("Ingen GSC-data ännu. Kör orchestratorn för att hämta data.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.line(
                gsc_df, x="Datum", y="Klick",
                title="Klick över tid",
                color_discrete_sequence=["#60a5fa"],
                template="plotly_dark",
            )
            fig.update_layout(
                paper_bgcolor="#1c1f26", plot_bgcolor="#1c1f26",
                margin=dict(t=40, b=20, l=10, r=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            fig2 = px.line(
                gsc_df, x="Datum", y="Visningar",
                title="Visningar över tid",
                color_discrete_sequence=["#c084fc"],
                template="plotly_dark",
            )
            fig2.update_layout(
                paper_bgcolor="#1c1f26", plot_bgcolor="#1c1f26",
                margin=dict(t=40, b=20, l=10, r=10),
            )
            st.plotly_chart(fig2, use_container_width=True)

        c3, c4 = st.columns(2)
        with c3:
            fig3 = px.line(
                gsc_df, x="Datum", y="Snitt Position",
                title="Snittposition (lägre = bättre)",
                color_discrete_sequence=["#4ade80"],
                template="plotly_dark",
            )
            fig3.update_yaxes(autorange="reversed")
            fig3.update_layout(
                paper_bgcolor="#1c1f26", plot_bgcolor="#1c1f26",
                margin=dict(t=40, b=20, l=10, r=10),
            )
            st.plotly_chart(fig3, use_container_width=True)

        with c4:
            fig4 = px.line(
                gsc_df, x="Datum", y="Snitt CTR %",
                title="CTR % över tid",
                color_discrete_sequence=["#fb923c"],
                template="plotly_dark",
            )
            fig4.update_layout(
                paper_bgcolor="#1c1f26", plot_bgcolor="#1c1f26",
                margin=dict(t=40, b=20, l=10, r=10),
            )
            st.plotly_chart(fig4, use_container_width=True)

# ── TAB 2: Content Pipeline ───────────────────────────────────────────────────

with tab2:
    if pipeline_df.empty:
        st.info("Inga publicerade artiklar ännu.")
    else:
        c1, c2, c3 = st.columns(3)
        type_counts = pipeline_df["Typ"].value_counts() if "Typ" in pipeline_df else pd.Series()
        c1.metric("Totalt publicerat", len(pipeline_df))
        c2.metric("Nya artiklar", int(type_counts.get("Ny artikel", 0)))
        c3.metric("Optimerade", int(type_counts.get("Optimerad", 0)))

        st.markdown("#### Senast publicerade")
        display_df = pipeline_df.copy()
        if "URL" in display_df.columns:
            display_df["Artikel"] = display_df.apply(
                lambda r: f'<a href="{r["URL"]}" target="_blank">{r.get("Titel", r["URL"])}</a>'
                if r.get("URL") else r.get("Titel", ""), axis=1
            )
        st.dataframe(
            display_df[["Publicerad", "Typ", "Titel", "Sökfras", "Status"]].tail(20).iloc[::-1],
            use_container_width=True,
            hide_index=True,
        )

# ── TAB 3: Optimeringskön ─────────────────────────────────────────────────────

with tab3:
    if queue_df.empty:
        st.info("Kön är tom.")
    else:
        if "Status" in queue_df.columns and "Typ" in queue_df.columns:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Väntar", len(queue_df[queue_df["Status"] == "Väntar"]))
            c2.metric("Quick Wins", len(queue_df[queue_df["Typ"] == "QUICK WIN"]))
            c3.metric("Content Gaps", len(queue_df[queue_df["Typ"] == "CONTENT GAP"]))
            c4.metric("Nya artiklar", len(queue_df[queue_df["Typ"] == "NY ARTIKEL"]))

            col_filter, _ = st.columns([2, 4])
            with col_filter:
                status_filter = st.selectbox("Filtrera status", ["Alla", "Väntar", "Behandlad"])

            filtered = queue_df if status_filter == "Alla" else queue_df[queue_df["Status"] == status_filter]

            st.dataframe(
                filtered[["Prioritet", "Typ", "URL/Sökfras", "Position", "Visningar", "CTR %", "Status"]],
                use_container_width=True,
                hide_index=True,
            )

# ── TAB 4: Aktivitetslogg ─────────────────────────────────────────────────────

with tab4:
    if log_df.empty:
        st.info("Ingen aktivitet loggad ännu.")
    else:
        st.dataframe(
            log_df.iloc[::-1].head(50),
            use_container_width=True,
            hide_index=True,
        )
