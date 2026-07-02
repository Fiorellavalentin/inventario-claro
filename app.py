import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from datetime import date, timedelta

st.set_page_config(page_title="Control de Inventario y Valoracion", layout="wide")

# ---------------------------------------------------------------------------
# CONEXION A SUPABASE (Postgres)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_engine():
    from urllib.parse import quote_plus
    pwd = quote_plus(st.secrets["DB_PASSWORD"])
    host = st.secrets["DB_HOST"]
    user = st.secrets["DB_USER"]
    url = f"postgresql+psycopg2://{user}:{pwd}@{host}:5432/postgres"
    return create_engine(url, pool_pre_ping=True)

engine = get_engine()

def run_query(sql, params=None):
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})

def run_exec(sql, params=None):
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})

# ---------------------------------------------------------------------------
# ACCESO CON CONTRASENA
# ---------------------------------------------------------------------------

def check_password():
