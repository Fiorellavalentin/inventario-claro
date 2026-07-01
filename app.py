import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import date, timedelta

st.set_page_config(page_title="Control de Inventario y Valoración", layout="wide")

# ---------------------------------------------------------------------------
# CONEXIÓN A SUPABASE (Postgres)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_engine():
    return create_engine(st.secrets["DB_URL"], pool_pre_ping=True)

engine = get_engine()

def run_query(sql, params=None):
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})

def run_exec(sql, params=None):
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})

# ---------------------------------------------------------------------------
# ACCESO CON CONTRASEÑA (protección básica del link público)
# ---------------------------------------------------------------------------

def check_password():
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False
    if st.session_state.auth_ok:
        return True
    st.title("🔒 Control de Inventario")
    pwd = st.text_input("Contraseña de acceso", type="password")
    if st.button("Ingresar"):
        if pwd == st.secrets.get("APP_PASSWORD", ""):
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    return False

if not check_password():
    st.stop()

# ---------------------------------------------------------------------------
# HELPERS DE NEGOCIO
# ---------------------------------------------------------------------------

def get_config():
    df = run_query("select * from config where id = 1")
    return df.iloc[0] if len(df) else {"dias_limite_nc": 30, "distribuidor": "Mi distribuidora"}

def money(n):
    if n is None or pd.isna(n):
        return "S/ 0.00"
    return f"S/ {float(n):,.2f}"

def margen_row(row):
    if row["precio_venta"] is None or pd.isna(row["precio_venta"]):
        return None
    return float(row["precio_venta"]) - float(row["precio_compra"])

def construir_correo(row, dias_limite, distribuidor):
    diferencia = abs(float(row["precio_venta"]) - float(row["precio_compra"]))
    return f"""Para: (correo de tu ejecutivo Claro)

Asunto: Solicitud de Nota de Credito pendiente - IMEI {row['imei']}

Estimados senores de Claro,

Por medio del presente, {distribuidor} solicita la emision de la Nota de Credito
correspondiente al siguiente equipo, dado que a la fecha no ha sido emitida de forma automatica:

- Marca / Modelo: {row['marca']} {row['modelo']}
- IMEI: {row['imei']}
- Fecha de compra: {row['fecha_compra']}
- Precio de compra: {money(row['precio_compra'])}
- Factura de compra: {row['factura_compra'] or 'N/D'}
- Fecha de venta al consumidor final: {row['fecha_venta']}
- Precio de venta: {money(row['precio_venta'])}
- Diferencia a favor del distribuidor: {money(diferencia)}

Segun la politica comercial vigente, esta diferencia debe ser reconocida mediante Nota de Credito.
Han transcurrido mas de {dias_limite} dias desde la venta sin que se haya emitido dicho documento,
por lo que solicitamos su regularizacion a la brevedad.

Quedamos atentos a su respuesta.

Saludos cordiales,
{distribuidor}"""

# ---------------------------------------------------------------------------
# SIDEBAR / NAVEGACION
# ---------------------------------------------------------------------------

st.sidebar.title("Control de Inventario")
st.sidebar.caption("Equipos & SIM - Valoracion")

page = st.sidebar.radio(
    "Ir a:",
    ["Dashboard", "Inventario", "Registrar compra", "Carga masiva",
     "Registrar venta", "Notas de credito", "Reclamos", "Configuracion"],
    label_visibility="collapsed",
)

if st.sidebar.button("Cerrar sesion"):
    st.session_state.auth_ok = False
    st.rerun()

cfg = get_config()
DIAS_LIMITE = int(cfg["dias_limite_nc"])
DISTRIBUIDOR = cfg["distribuidor"]

# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------

if page == "Dashboard":
    st.title("Dashboard")
    st.caption("Resumen del inventario y valoracion de compra/venta.")
    equipos = run_query("select * from equipos")
    if len(equipos) == 0:
        st.info("Todavia no hay equipos registrados. Ve a 'Registrar compra' para empezar.")
    else:
        equipos["margen"] = equipos.apply(margen_row, axis=1)
        en_stock = equipos[equipos["estado"] == "stock"]
        mes_actual = date.today().strftime("%Y-%m")
        ventas_mes = equipos[equipos["fecha_venta"].astype(str).str.startswith(mes_actual)]
        margen_mes = ventas_mes["margen"].sum()
        perdidas = equipos[equipos["margen"] < 0]
        nc_pendientes = equipos[equipos["estado_nc"] == "pendiente"]
        vencidos = nc_pendientes[
            pd.to_datetime(nc_pendientes["fecha_limite_nc"]) < pd.Timestamp(date.today())
        ]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Equipos en stock", len(en_stock), f"Valor: {money(en_stock['precio_compra'].sum())}")
        c2.metric("Ventas este mes", len(ventas_mes), f"Margen: {money(margen_mes)}")
        c3.metric("Casos con perdida", len(perdidas))
        c4.metric("NC pendientes", len(nc_pendientes), f"{money(nc_pendientes['monto_nc'].sum())} por recuperar")
        if len(vencidos):
            st.error(f"Atencion: {len(vencidos)} equipo(s) con NC vencida sin respuesta de Claro. Revisa la pestana 'Notas de credito'.")
        st.subheader("Reclamos activos")
        reclamos = run_query("select * from reclamos where estado = 'pendiente' order by fecha_envio desc")
        if len(reclamos) == 0:
            st.caption("No hay reclamos pendientes de respuesta.")
        else:
            st.dataframe(reclamos[["imei", "modelo", "fecha_envio", "motivo"]], use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# INVENTARIO
# ---------------------------------------------------------------------------

elif page == "Inventario":
    st.title("Inventario")
    st.caption("Todos los equipos y SIM registrados.")
    col1, col2, col3 = st.columns(3)
    busca = col1.text_input("Buscar por IMEI / ICCID / modelo")
    f_estado = col2.selectbox("Estado", ["Todos", "stock", "vendido"])
    f_nc = col3.selectbox("Estado NC", ["Todos", "pendiente", "emitida", "reclamada", "no_aplica"])
    equipos = run_query("select * from equipos order by created_at desc")
    if len(equipos):
        equipos["margen"] = equipos.apply(margen_row, axis=1)
        if busca:
            b = busca.lower()
            mask = (
                equipos["imei"].astype(str).str.lower().str.contains(b, na=False)
                | equipos["iccid"].astype(str).str.lower().str.contains(b, na=False)
                | equipos["modelo"].astype(str).str.lower().str.contains(b, na=False)
            )
            equipos = equipos[mask]
        if f_estado != "Todos":
            equipos = equipos[equipos["estado"] == f_estado]
        if f_nc != "Todos":
            equipos = equipos[equipos["estado_nc"] == f_nc]
        show = equipos[["estado", "marca", "modelo", "imei", "iccid", "precio_compra",
                         "fecha_compra", "precio_venta", "fecha_venta", "margen", "estado_nc"]]
        st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.info("No hay equipos registrados todavia.")

# ---------------------------------------------------------------------------
# REGISTRAR COMPRA
# ---------------------------------------------------------------------------

elif page == "Registrar compra":
    st.title("Registrar compra")
    st.caption("Ingresa un equipo o SIM comprado a Claro para sumarlo al inventario.")
    with st.form("form_compra", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        categoria = c1.selectbox("Categoria", ["equipo", "sim", "equipo+chip"])
        marca = c2.text_input("Marca")
        modelo = c3.text_input("Modelo")
        c4, c5, c6 = st.columns(3)
        imei = c4.text_input("IMEI")
        iccid = c5.text_input("ICCID")
        factura = c6.text_input("N de factura Claro")
        c7, c8, c9 = st.columns(3)
        fecha_compra = c7.date_input("Fecha de compra", value=date.today())
        precio_compra = c8.number_input("Precio de compra (S/)", min_value=0.0, step=0.01)
        notas = c9.text_input("Notas (opcional)")
        submitted = st.form_submit_button("Registrar compra")
        if submitted:
            if not marca or not modelo or precio_compra <= 0:
                st.error("Completa marca, modelo y precio de compra.")
            elif categoria != "sim" and not imei:
                st.error("Ingresa el IMEI del equipo.")
            elif categoria != "equipo" and not iccid:
                st.error("Ingresa el ICCID del chip.")
            else:
                run_exec(
                    """insert into equipos
                       (imei, iccid, marca, modelo, categoria, fecha_compra, precio_compra, factura_compra, notas)
                       values (:imei, :iccid, :marca, :modelo, :categoria, :fecha_compra, :precio_compra, :factura, :notas)""",
                    dict(imei=imei, iccid=iccid, marca=marca, modelo=modelo, categoria=categoria,
                         fecha_compra=fecha_compra, precio_compra=precio_compra, factura=factura, notas=notas),
                )
                st.success("Compra registrada correctamente.")

# ---------------------------------------------------------------------------
# CARGA MASIVA
# ---------------------------------------------------------------------------

elif page == "Carga masiva":
    st.title("Carga masiva")
    st.caption("Registra en un solo paso todos los SIM o equipos de una misma factura de compra.")
    st.markdown("**1. Datos comunes de la factura**")
    c1, c2, c3 = st.columns(3)
    categoria_m = c1.selectbox("Categoria", ["sim", "equipo", "equipo+chip"])
    factura_m = c2.text_input("N de factura Claro")
    fecha_m = c3.date_input("Fecha de compra", value=date.today())
    c4, c5, c6 = st.columns(3)
    marca_m = c4.text_input("Marca (comun)", value="Claro" if categoria_m == "sim" else "")
    modelo_m = c5.text_input("Modelo (comun)", value="SIM Card" if categoria_m == "sim" else "")
    precio_m = c6.number_input("Precio de compra unitario (S/)", min_value=0.0, step=0.01)
    st.markdown("**2. Lista de codigos**")
    metodo = st.radio("Metodo de carga", ["Subir archivo Excel/CSV", "Pegar lista de codigos"], horizontal=True)
    df_carga = None
    if metodo == "Subir archivo Excel/CSV":
        archivo = st.file_uploader("Archivo", type=["xlsx", "xls", "csv"])
        if archivo is not None:
            try:
                if archivo.name.lower().endswith(".csv"):
                    df_carga = pd.read_csv(archivo, dtype=str)
                else:
                    df_carga = pd.read_excel(archivo, dtype=str)
                df_carga.columns = [str(c).strip().upper() for c in df_carga.columns]
            except Exception as e:
                st.error(f"No se pudo leer el archivo: {e}")
    else:
        etiqueta = "ICCID" if categoria_m == "sim" else "IMEI"
        pegado = st.text_area(f"Pega aqui los {etiqueta} (uno por linea)", height=200)
        if pegado.strip():
            codigos = [l.strip() for l in pegado.splitlines() if l.strip()]
            col = "ICCID" if categoria_m == "sim" else "IMEI"
            df_carga = pd.DataFrame({col: codigos})
    if df_carga is not None and len(df_carga):
        for col in df_carga.columns:
            df_carga[col] = df_carga[col].astype(str).str.strip().replace({"nan": "", "None": ""})
        col_clave = "ICCID" if categoria_m == "sim" else "IMEI"
        if col_clave not in df_carga.columns:
            st.error(f"El archivo debe tener una columna llamada {col_clave}.")
        else:
            df_carga = df_carga[df_carga[col_clave] != ""].copy()
            problemas = []
            dups_archivo = df_carga[df_carga.duplicated(subset=[col_clave], keep=False)]
            if len(dups_archivo):
                problemas.append(f"{dups_archivo[col_clave].nunique()} codigo(s) repetidos dentro del archivo.")
            codigos_lista = df_carga[col_clave].tolist()
            campo_db = "iccid" if categoria_m == "sim" else "imei"
            existentes = run_query(
                f"select {campo_db} from equipos where {campo_db} = any(:codigos)",
                {"codigos": codigos_lista},
            )
            ya_registrados = set(existentes[campo_db].tolist()) if len(existentes) else set()
            if ya_registrados:
                problemas.append(f"{len(ya_registrados)} codigo(s) ya existen en el inventario y seran omitidos.")
            largo_esperado = 19 if categoria_m == "sim" else 15
            sospechosos = df_carga[df_carga[col_clave].str.len().between(largo_esperado - 1, largo_esperado + 1) == False]
            if len(sospechosos):
                problemas.append(f"{len(sospechosos)} codigo(s) tienen largo distinto al esperado (~{largo_esperado} digitos).")
            for p in problemas:
                st.warning(p)
            df_final = df_carga.drop_duplicates(subset=[col_clave], keep="first")
            df_final = df_final[~df_final[col_clave].isin(ya_registrados)]
            st.markdown(f"**3. Vista previa** - {len(df_final)} registro(s) listos para cargar")
            st.dataframe(df_final.head(50), use_container_width=True, hide_index=True)
            puede_cargar = len(df_final) > 0 and precio_m > 0 and marca_m and modelo_m
            if not puede_cargar and len(df_final) > 0:
                st.info("Completa marca, modelo y precio unitario para habilitar la carga.")
            if st.button(f"Cargar {len(df_final)} registro(s) al inventario", disabled=not puede_cargar, type="primary"):
                filas = []
                for _, r in df_final.iterrows():
                    filas.append(dict(
                        imei=r.get("IMEI", "") if categoria_m != "sim" else "",
                        iccid=r.get("ICCID", "") if categoria_m != "equipo" else "",
                        marca=r.get("MARCA") or marca_m,
                        modelo=r.get("MODELO") or modelo_m,
                        categoria=categoria_m,
                        fecha_compra=fecha_m,
                        precio_compra=float(r.get("PRECIO_COMPRA") or precio_m),
                        factura=factura_m,
                        notas="Carga masiva",
                    ))
                with engine.begin() as conn:
                    conn.execute(
                        text("""insert into equipos
                                (imei, iccid, marca, modelo, categoria, fecha_compra, precio_compra, factura_compra, notas)
                                values (:imei, :iccid, :marca, :modelo, :categoria, :fecha_compra, :precio_compra, :factura, :notas)"""),
                        filas,
                    )
                st.success(f"{len(filas)} registro(s) cargados correctamente (factura {factura_m or 'sin numero'}).")
                st.balloons()

# ---------------------------------------------------------------------------
# REGISTRAR VENTA
# ---------------------------------------------------------------------------

elif page == "Registrar venta":
    st.title("Registrar venta")
    st.caption("Selecciona un equipo en stock y registra su venta al consumidor final.")
    en_stock = run_query("select * from equipos where estado = 'stock' order by created_at desc")
    if len(en_stock) == 0:
        st.info("No hay equipos en stock. Registra una compra primero.")
    else:
        opciones = {
            f"{r['marca']} {r['modelo']} - IMEI {r['imei'] or 's/n'} - Compra {money(r['precio_compra'])}": r["id"]
            for _, r in en_stock.iterrows()
        }
        elegido = st.selectbox("Equipo / SIM", list(opciones.keys()))
        eq_id = opciones[elegido]
        eq_row = en_stock[en_stock["id"] == eq_id].iloc[0]
        with st.form("form_venta"):
            c1, c2, c3 = st.columns(3)
            fecha_venta = c1.date_input("Fecha de venta", value=date.today())
            precio_venta = c2.number_input("Precio de venta (S/)", min_value=0.0, step=0.01)
            comprobante = c3.text_input("Comprobante")
            cliente = st.text_input("Cliente")
            if precio_venta > 0:
                m = precio_venta - float(eq_row["precio_compra"])
                if m < 0:
                    st.warning(f"Margen negativo: {money(m)}. Quedara marcado como pendiente de Nota de Credito de Claro.")
                else:
                    st.success(f"Margen positivo: {money(m)}")
            submitted = st.form_submit_button("Registrar venta")
            if submitted:
                if precio_venta <= 0:
                    st.error("Ingresa el precio de venta.")
                else:
                    m = precio_venta - float(eq_row["precio_compra"])
                    estado_nc = "no_aplica"
                    fecha_limite = None
                    monto_nc = None
                    if m < 0:
                        estado_nc = "pendiente"
                        fecha_limite = fecha_venta + timedelta(days=DIAS_LIMITE)
                        monto_nc = abs(m)
                    run_exec(
                        """update equipos set
                           fecha_venta=:fecha_venta, precio_venta=:precio_venta, cliente=:cliente,
                           comprobante_venta=:comprobante, estado='vendido',
                           estado_nc=:estado_nc, fecha_limite_nc=:fecha_limite, monto_nc=:monto_nc
                           where id=:id""",
                        dict(fecha_venta=fecha_venta, precio_venta=precio_venta, cliente=cliente,
                             comprobante=comprobante, estado_nc=estado_nc, fecha_limite=fecha_limite,
                             monto_nc=monto_nc, id=int(eq_id)),
                    )
                    st.success("Venta registrada correctamente.")
                    st.rerun()

# ---------------------------------------------------------------------------
# NOTAS DE CREDITO
# ---------------------------------------------------------------------------

elif page == "Notas de credito":
    st.title("Notas de credito")
    st.caption(f"Equipos vendidos con margen negativo. Plazo configurado: {DIAS_LIMITE} dias desde la venta.")
    equipos = run_query("select * from equipos where precio_venta is not null")
    if len(equipos):
        equipos["margen"] = equipos.apply(margen_row, axis=1)
        casos = equipos[equipos["margen"] < 0].copy()
    else:
        casos = equipos
    if len(casos) == 0:
        st.info("No hay casos con margen negativo registrados.")
    else:
        for _, row in casos.iterrows():
            dif = abs(row["margen"])
            vencido = (row["estado_nc"] == "pendiente" and row["fecha_limite_nc"] is not None and
                      pd.Timestamp(row["fecha_limite_nc"]) < pd.Timestamp(date.today()))
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
                c1.write(f"**{row['marca']} {row['modelo']}**")
                c1.caption(f"IMEI {row['imei']}")
                c2.write(f"Venta: {row['fecha_venta']}")
                c2.write(f"Diferencia: {money(dif)}")
                c3.write(f"Plazo: {row['fecha_limite_nc']}")
                if vencido:
                    c3.error("Vencido")
                c4.write(f"Estado: {row['estado_nc']}")
                if row["estado_nc"] == "pendiente":
                    col_a, col_b = c4.columns(2)
                    with col_a.popover("Marcar emitida"):
                        monto = st.number_input("Monto NC (S/)", value=float(dif), key=f"monto_{row['id']}")
                        fecha_em = st.date_input("Fecha emision", value=date.today(), key=f"fecha_{row['id']}")
                        if st.button("Guardar", key=f"guardar_{row['id']}"):
                            run_exec(
                                "update equipos set estado_nc='emitida', monto_nc=:m, fecha_emision_nc=:f where id=:id",
                                dict(m=monto, f=fecha_em, id=int(row["id"])),
                            )
                            st.rerun()
                    if vencido:
                        if col_b.button("Generar reclamo", key=f"reclamo_{row['id']}"):
                            email = construir_correo(row, DIAS_LIMITE, DISTRIBUIDOR)
                            run_exec("update equipos set estado_nc='reclamada' where id=:id", dict(id=int(row["id"])))
                            run_exec(
                                """insert into reclamos (equipo_id, imei, modelo, motivo, email_borrador)
                                   values (:eq, :imei, :modelo, :motivo, :email)""",
                                dict(eq=int(row["id"]), imei=row["imei"], modelo=row["modelo"],
                                     motivo="Nota de credito no emitida dentro del plazo", email=email),
                            )
                            st.success("Reclamo generado. Revisalo en la pestana Reclamos.")
                            st.rerun()

# ---------------------------------------------------------------------------
# RECLAMOS
# ---------------------------------------------------------------------------

elif page == "Reclamos":
    st.title("Reclamos a Claro")
    st.caption("Casos donde la Nota de Credito no fue emitida a tiempo y se envio un reclamo.")
    reclamos = run_query("select * from reclamos order by fecha_envio desc")
    if len(reclamos) == 0:
        st.info("No hay reclamos generados todavia.")
    else:
        for _, r in reclamos.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 2, 2])
                c1.write(f"**{r['modelo']}**")
                c1.caption(f"IMEI {r['imei']}")
                c2.write(f"Enviado: {r['fecha_envio']}")
                nuevo_estado = c3.selectbox(
                    "Estado", ["pendiente", "enviado", "resuelto"],
                    index=["pendiente", "enviado", "resuelto"].index(r["estado"]),
                    key=f"estado_{r['id']}",
                )
                if nuevo_estado != r["estado"]:
                    fecha_res = date.today() if nuevo_estado == "resuelto" else None
                    run_exec("update reclamos set estado=:e, fecha_resolucion=:f where id=:id",
                             dict(e=nuevo_estado, f=fecha_res, id=int(r["id"])))
                    st.rerun()
                with st.expander("Ver borrador de correo"):
                    st.text_area("Correo", value=r["email_borrador"], height=280, key=f"email_{r['id']}")

# ---------------------------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------------------------

elif page == "Configuracion":
    st.title("Configuracion")
    st.caption("Ajustes del calculo de plazos y datos del distribuidor.")
    with st.form("form_config"):
        distribuidor = st.text_input("Nombre del distribuidor", value=DISTRIBUIDOR)
        dias = st.number_input("Plazo esperado de NC (dias)", min_value=1, value=DIAS_LIMITE)
        if st.form_submit_button("Guardar configuracion"):
            run_exec("update config set distribuidor=:d, dias_limite_nc=:n where id=1",
                     dict(d=distribuidor, n=int(dias)))
            st.success("Configuracion guardada.")
            st.rerun()
