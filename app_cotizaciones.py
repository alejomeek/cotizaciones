import streamlit as st
import pandas as pd
from datetime import date, datetime
from PIL import Image
from fpdf import FPDF
import requests
from io import BytesIO
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Cotizaciones - Jugando y Educando",
    page_icon="🧸",
    layout="wide"
)

# --- INICIALIZACIÓN DE FIREBASE (Código seguro para la nube) ---
@st.cache_resource
def init_firebase():
    """Inicializa la conexión con Firebase de forma segura."""
    try:
        if 'firebase_secrets' in st.secrets:
            creds_dict = dict(st.secrets["firebase_secrets"])
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        elif os.path.exists("firebase_secrets.json"):
            with open("firebase_secrets.json", "r") as f:
                creds_dict = json.load(f)
        else:
            st.error("No se encontraron credenciales de Firebase.")
            return None

        if not firebase_admin._apps:
            creds = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(creds)
        
        return firestore.client()
    except Exception as e:
        st.error(f"Fallo al inicializar Firebase: {e}")
        return None

db = init_firebase()

# --- CLASE PDF PERSONALIZADA ---
class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.color_primary = (4, 76, 125)
        self.color_secondary = (240, 240, 240)
        self.color_text = (50, 50, 50)
        self.color_border = (220, 220, 220)

    def header(self):
        try:
            self.add_font('Lato', '', 'Lato-Regular.ttf', uni=True)
            self.add_font('Lato', 'B', 'Lato-Bold.ttf', uni=True)
            self.add_font('Lato', 'I', 'Lato-Italic.ttf', uni=True)
            self.current_font_family = 'Lato'
        except RuntimeError:
            self.current_font_family = 'Arial'

        try:
            self.image("logo_transparente.png", 10, 8, 45)
        except FileNotFoundError:
            self.set_font(self.current_font_family, "B", 14)
            self.set_xy(10, 15)
            self.cell(0, 10, "JUGANDO Y EDUCANDO")

        self.set_font(self.current_font_family, "B", 9)
        self.set_text_color(*self.color_text)
        info_x = 120
        self.set_xy(info_x, 10)
        self.cell(0, 5, "DIDACTICOS JUGANDO Y EDUCANDO SAS", 0, 1, 'R')
        self.set_font(self.current_font_family, "", 9)
        self.set_x(info_x)
        self.cell(0, 5, "NIT: 901144615-6", 0, 1, 'R')
        self.set_x(info_x)
        self.cell(0, 5, "CEL: 3153357921", 0, 1, 'R')
        self.set_x(info_x)
        self.cell(0, 5, "jugandoyeducando@hotmail.com", 0, 1, 'R')
        self.set_x(info_x)
        self.cell(0, 5, "Avenida 19 # 114A - 22, Bogota", 0, 1, 'R')

        self.set_y(45)
        self.set_font(self.current_font_family, "B", 22)
        self.set_text_color(*self.color_primary)
        self.cell(0, 10, "COTIZACIÓN", 0, 1, 'L')
        self.set_line_width(0.5)
        self.set_draw_color(*self.color_primary)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def draw_client_info(self, data):
        self.ln(5)
        self.set_font(self.current_font_family, "B", 11)
        self.set_text_color(*self.color_primary)
        self.cell(0, 8, "Información del Cliente", 0, 1, 'L')
        self.set_font(self.current_font_family, "", 10)
        self.set_text_color(*self.color_text)
        y_start = self.get_y()
        self.set_xy(10, y_start)
        self.cell(25, 6, "Cliente:", 0, 0, 'L')
        self.set_font(self.current_font_family, "B", 10)
        self.multi_cell(75, 6, data['cliente_nombre'], 0, 'L')
        self.set_font(self.current_font_family, "", 10)
        self.set_xy(10, self.get_y())
        self.cell(25, 6, "NIT/CC:", 0, 0, 'L')
        self.multi_cell(75, 6, data['cliente_nit'], 0, 'L')
        self.set_xy(10, self.get_y())
        self.cell(25, 6, "Dirección:", 0, 0, 'L')
        self.multi_cell(75, 6, f"{data['cliente_dir']}, {data['cliente_ciudad']}", 0, 'L')
        y_left_end = self.get_y()
        self.set_xy(110, y_start)
        self.cell(25, 6, "Fecha:", 0, 0, 'L')
        self.multi_cell(75, 6, data['fecha'], 0, 'L')
        self.set_xy(110, self.get_y())
        self.cell(25, 6, "Teléfono:", 0, 0, 'L')
        self.multi_cell(75, 6, data['cliente_tel'], 0, 'L')
        self.set_xy(110, self.get_y())
        self.cell(25, 6, "Vigencia:", 0, 0, 'L')
        self.multi_cell(75, 6, data['vigencia'], 0, 'L')
        y_right_end = self.get_y()
        self.set_y(max(y_left_end, y_right_end) + 5)

    def get_multicell_lines(self, text, width):
        self.set_font(self.current_font_family, "", 9)
        words = text.split(' ')
        lines_count = 1
        current_line_w = 0
        space_w = self.get_string_width(' ')
        for word in words:
            word_w = self.get_string_width(word)
            if word_w > width:
                lines_count += int(word_w / width)
                word_w = word_w % width
            if current_line_w + word_w + space_w < width:
                current_line_w += word_w + space_w
            else:
                lines_count += 1
                current_line_w = word_w + space_w
        return lines_count

    def draw_table_header(self, col_widths):
        self.set_font(self.current_font_family, "B", 9)
        self.set_fill_color(*self.color_primary)
        self.set_text_color(255, 255, 255)
        self.set_draw_color(*self.color_primary)
        self.set_line_width(0.3)
        self.cell(col_widths['img'], 8, "IMAGEN", 'T', 0, 'C', 1)
        self.cell(col_widths['name'], 8, "PRODUCTO", 'T', 0, 'C', 1)
        self.cell(col_widths['sku'], 8, "CÓDIGO", 'T', 0, 'C', 1)
        self.cell(col_widths['qty'], 8, "UNDS.", 'T', 0, 'C', 1)
        self.cell(col_widths['price'], 8, "VLR. UNITARIO", 'T', 0, 'C', 1)
        self.cell(col_widths['total'], 8, "VALOR TOTAL", 'T', 1, 'C', 1)

    # --- CORREGIDO V2 ---
    def draw_table_row(self, item, col_widths, fill=False):
        self.set_font(self.current_font_family, "", 9)
        self.set_text_color(*self.color_text)
        self.set_draw_color(*self.color_border)
        self.set_fill_color(*self.color_secondary)
        
        line_height = 5
        num_lines = self.get_multicell_lines(item['nombre'], col_widths['name'] - 2)
        name_height = num_lines * line_height
        row_height = max(30, name_height + 4)

        # Comprueba si la fila cabe en la página actual
        if self.get_y() + row_height > 270:
            self.add_page()
            self.draw_table_header(col_widths)

        # Guarda las coordenadas de inicio de la fila
        x_start = self.get_x()
        y_start = self.get_y()

        # Dibuja la imagen
        try:
            response = requests.get(item['imagen_url'], timeout=5)
            if response.status_code == 200:
                img_bytes = BytesIO(response.content)
                self.image(img_bytes, x=x_start + 2, y=y_start + 2, w=col_widths['img'] - 4, h=row_height - 4)
        except Exception:
            v_offset_placeholder = (row_height - 4) / 2
            self.set_xy(x_start, y_start + v_offset_placeholder)
            self.cell(col_widths['img'], 4, "S/I", 0, 0, 'C')

        # Dibuja el nombre del producto (multi-línea)
        name_v_offset = (row_height - name_height) / 2
        self.set_xy(x_start + col_widths['img'], y_start + name_v_offset)
        self.multi_cell(col_widths['name'], line_height, item['nombre'], border=0, align='C')
        
        # Calcula la posición Y para las celdas de una sola línea
        text_height = self.font_size
        cell_v_offset = (row_height - text_height) / 2
        
        # Dibuja las celdas de una sola línea usando un flujo continuo
        self.set_y(y_start + cell_v_offset) # Establece la altura Y una sola vez
        self.set_x(x_start + col_widths['img'] + col_widths['name']) # Posición inicial (columna SKU)
        
        self.cell(col_widths['sku'], text_height, item['sku'], 0, 0, 'C')
        self.cell(col_widths['qty'], text_height, str(item['cantidad']), 0, 0, 'C')
        self.cell(col_widths['price'], text_height, format_currency(item['precio_unitario']), 0, 0, 'R')
        self.cell(col_widths['total'], text_height, format_currency(item['valor_total']), 0, 0, 'R')

        # Dibuja el fondo y el borde de la fila completa al final
        self.set_xy(x_start, y_start)
        self.cell(col_widths['img'], row_height, "", 'B', 0, 'C', fill)
        self.cell(col_widths['name'], row_height, "", 'B', 0, 'C', fill)
        self.cell(col_widths['sku'], row_height, "", 'B', 0, 'C', fill)
        self.cell(col_widths['qty'], row_height, "", 'B', 0, 'C', fill)
        self.cell(col_widths['price'], row_height, "", 'B', 0, 'R', fill)
        self.cell(col_widths['total'], row_height, "", 'B', 1, 'R', fill)


    def footer(self):
        self.set_y(-15)
        self.set_font(self.current_font_family, "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Página {self.page_no()}", 0, 0, 'C')

# --- FUNCIONES DE FIREBASE ---
@st.cache_data(ttl=60)
def get_quotes_list(_db, tienda):
    """Obtiene la lista de cotizaciones de Firestore, filtrada por tienda."""
    if not _db: return {}
    quotes_ref = _db.collection('cotizaciones').where('tienda', '==', tienda).stream()
    quotes_dict = {}
    for quote in quotes_ref:
        quote_data = quote.to_dict()
        client_name = quote_data.get('cliente_nombre', 'N/A')
        quote_date = quote_data.get('fecha', 'N/A')
        label = f"{client_name} - {quote_date}"
        quotes_dict[label] = quote.id
    return quotes_dict

def save_quote(_db, quote_data, quote_id=None):
    """Guarda o actualiza una cotización en Firestore."""
    if not _db:
        st.error("Conexión a la base de datos no disponible.")
        return
    if 'tienda' not in quote_data or not quote_data['tienda']:
        st.error("Error: No se puede guardar la cotización sin una tienda asignada.")
        return
    try:
        if quote_id:
            _db.collection('cotizaciones').document(quote_id).set(quote_data)
            st.success(f"¡Cotización '{quote_data['cliente_nombre']}' actualizada con éxito!")
        else:
            _db.collection('cotizaciones').add(quote_data)
            st.success(f"¡Cotización '{quote_data['cliente_nombre']}' guardada como nueva!")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al guardar la cotización: {e}")

def delete_quote(_db, quote_id):
    """Elimina una cotización de Firestore."""
    if not _db:
        st.error("Conexión a la base de datos no disponible.")
        return
    try:
        _db.collection('cotizaciones').document(quote_id).delete()
        st.success("¡Cotización eliminada con éxito!")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al eliminar la cotización: {e}")

# --- FUNCIONES AUXILIARES ---
@st.cache_data
def process_wix_csv(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file, delimiter=',', dtype={'sku': str}, engine='python')
        df_processed = df[['sku', 'name', 'price', 'productImageUrl', 'inventory']].copy()
        df_processed.dropna(subset=['sku', 'name'], inplace=True)
        df_processed['inventory'] = pd.to_numeric(df_processed['inventory'], errors='coerce').fillna(0).astype(int)
        def get_main_image_url(url_str):
            if not isinstance(url_str, str) or url_str == "": return "https://placehold.co/100x100/EEE/333?text=S/I"
            return f"https://static.wixstatic.com/media/{url_str.split(';')[0]}"
        df_processed['imagen_url'] = df_processed['productImageUrl'].apply(get_main_image_url)
        df_processed.rename(columns={'name': 'nombre', 'price': 'precio_iva_incluido'}, inplace=True)
        return df_processed[['sku', 'nombre', 'precio_iva_incluido', 'imagen_url', 'inventory']]
    except Exception as e:
        st.error(f"❌ Error al procesar CSV: {e}")
        return None

def format_currency(value):
    if not isinstance(value, (int, float)): return "$0"
    return f"${value:,.0f}".replace(",", ".")

def remove_item(sku):
    if sku in st.session_state.quote_items: del st.session_state.quote_items[sku]

def generate_pdf_content(quote_data):
    pdf = PDF('P', 'mm', 'A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.draw_client_info(quote_data)
    pdf.ln(5)
    col_widths = {'img': 30, 'name': 70, 'sku': 20, 'qty': 15, 'price': 25, 'total': 30}
    pdf.draw_table_header(col_widths)
    fill = True
    for item in quote_data['items'].values():
        pdf.draw_table_row(item, col_widths, fill)
        fill = not fill
    if pdf.get_y() > 225: pdf.add_page()
    total_label_x = 100
    totals_y_start = pdf.get_y() + 5 
    pdf.set_font(pdf.current_font_family, "", 10)
    pdf.set_text_color(*pdf.color_text)
    pdf.set_xy(total_label_x, totals_y_start)
    pdf.cell(70, 8, "SUBTOTAL", 0, 0, 'R')
    pdf.set_font(pdf.current_font_family, "B", 10)
    pdf.cell(30, 8, format_currency(quote_data['subtotal']), 0, 1, 'R')
    pdf.set_font(pdf.current_font_family, "", 10)
    pdf.set_x(total_label_x)
    pdf.cell(70, 8, "FLETE", 0, 0, 'R')
    pdf.set_font(pdf.current_font_family, "B", 10)
    pdf.cell(30, 8, quote_data['flete_str'], 0, 1, 'R')
    pdf.set_font(pdf.current_font_family, "", 10)
    pdf.set_x(total_label_x)
    pdf.cell(70, 8, "TOTAL UNIDADES", 0, 0, 'R')
    pdf.set_font(pdf.current_font_family, "B", 10)
    pdf.cell(30, 8, str(quote_data['total_unidades']), 0, 1, 'R')
    pdf.set_x(total_label_x)
    pdf.set_draw_color(*pdf.color_border)
    pdf.line(total_label_x + 5, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)
    pdf.set_font(pdf.current_font_family, "B", 11)
    pdf.set_text_color(*pdf.color_primary)
    pdf.set_x(total_label_x)
    pdf.cell(70, 10, "TOTAL COTIZACION INCLUIDO IVA", 0, 0, 'R')
    pdf.set_font(pdf.current_font_family, "B", 12)
    pdf.cell(30, 10, format_currency(quote_data['total_cotizacion']), 0, 1, 'R')
    return bytes(pdf.output())

# --- INICIALIZACIÓN DEL ESTADO DE SESIÓN ---
def init_session_state():
    """Inicializa las variables necesarias en el estado de la sesión."""
    st.session_state.setdefault('tienda_seleccionada', None)
    st.session_state.setdefault('quote_items', {})
    st.session_state.setdefault('current_quote_id', None)
    st.session_state.setdefault('cliente_nombre', "")
    st.session_state.setdefault('cliente_nit', "")
    st.session_state.setdefault('cliente_ciudad', "")
    st.session_state.setdefault('cliente_tel', "")
    st.session_state.setdefault('cliente_email', "")
    st.session_state.setdefault('cliente_dir', "")
    st.session_state.setdefault('forma_pago', "Transferencia bancaria (pago anticipado)")
    st.session_state.setdefault('vigencia', "5 DÍAS HÁBILES")

init_session_state()

def clear_state():
    """Limpia el estado para una nueva cotización. NO limpia la tienda."""
    st.session_state.quote_items = {}
    st.session_state.current_quote_id = None
    st.session_state.cliente_nombre = ""
    st.session_state.cliente_nit = ""
    st.session_state.cliente_ciudad = ""
    st.session_state.cliente_tel = ""
    st.session_state.cliente_email = ""
    st.session_state.cliente_dir = ""
    st.session_state.forma_pago = "Transferencia bancaria (pago anticipado)"
    st.session_state.vigencia = "5 DÍAS HÁBILES"
    st.success("Formulario limpiado. Listo para una nueva cotización.")

# --- BARRA LATERAL PARA GESTIÓN DE COTIZACIONES ---
with st.sidebar:
    st.title("Gestión de Cotizaciones")

    tiendas = ["Oviedo", "Barranquilla"]
    st.session_state.tienda_seleccionada = st.radio(
        "Selecciona tu tienda:",
        tiendas,
        index=tiendas.index(st.session_state.tienda_seleccionada) if st.session_state.tienda_seleccionada else None,
        horizontal=True,
    )
    
    if st.session_state.tienda_seleccionada:
        st.success(f"Tienda seleccionada: **{st.session_state.tienda_seleccionada}**")
        st.divider()

        if st.button("➕ Nueva Cotización", use_container_width=True):
            clear_state()

        st.divider()
        
        if db:
            quotes_dict = get_quotes_list(db, st.session_state.tienda_seleccionada)
            if quotes_dict:
                selected_quote_label = st.selectbox(
                    "Cargar Cotización Existente",
                    options=list(quotes_dict.keys()),
                    index=None,
                    placeholder="Selecciona una cotización..."
                )

                if st.button("📥 Cargar Cotización", use_container_width=True) and selected_quote_label:
                    quote_id_to_load = quotes_dict[selected_quote_label]
                    quote_data = db.collection('cotizaciones').document(quote_id_to_load).get().to_dict()
                    
                    st.session_state.current_quote_id = quote_id_to_load
                    st.session_state.cliente_nombre = quote_data.get('cliente_nombre', '')
                    st.session_state.cliente_nit = quote_data.get('cliente_nit', '')
                    st.session_state.cliente_ciudad = quote_data.get('cliente_ciudad', '')
                    st.session_state.cliente_tel = quote_data.get('cliente_tel', '')
                    st.session_state.cliente_email = quote_data.get('cliente_email', '')
                    st.session_state.cliente_dir = quote_data.get('cliente_dir', '')
                    st.session_state.forma_pago = quote_data.get('forma_pago', "Transferencia bancaria (pago anticipado)")
                    st.session_state.vigencia = quote_data.get('vigencia', "5 DÍAS HÁBILES")
                    st.session_state.quote_items = quote_data.get('items', {})
                    st.success(f"Cotización de '{selected_quote_label}' cargada.")
                    st.rerun()

        st.divider()
        
        def collect_data_to_save():
            return {
                'tienda': st.session_state.tienda_seleccionada,
                'fecha': date.today().strftime("%d/%m/%Y"),
                'cliente_nombre': st.session_state.cliente_nombre,
                'cliente_nit': st.session_state.cliente_nit,
                'cliente_ciudad': st.session_state.cliente_ciudad,
                'cliente_tel': st.session_state.cliente_tel,
                'cliente_email': st.session_state.cliente_email,
                'cliente_dir': st.session_state.cliente_dir,
                'forma_pago': st.session_state.forma_pago,
                'vigencia': st.session_state.vigencia,
                'items': st.session_state.quote_items
            }

        if st.session_state.get('current_quote_id'):
            st.info(f"Modificando: {st.session_state.cliente_nombre}")
            if st.button("💾 Guardar Cambios", use_container_width=True, type="primary"):
                quote_data_to_save = collect_data_to_save()
                save_quote(db, quote_data_to_save, st.session_state.current_quote_id)
                
        if st.button("💾 Guardar como Nueva Cotización", use_container_width=True):
            if not st.session_state.cliente_nombre:
                st.warning("Por favor, introduce al menos el nombre del cliente.")
            else:
                quote_data_to_save = collect_data_to_save()
                save_quote(db, quote_data_to_save, None)

        if st.session_state.get('current_quote_id'):
            st.divider()
            if st.button("🗑️ Eliminar Cotización", use_container_width=True):
                delete_quote(db, st.session_state.current_quote_id)
                clear_state()
                st.rerun()

# --- UI PRINCIPAL DE LA APP ---
if not st.session_state.tienda_seleccionada:
    st.info("👋 ¡Bienvenido! Por favor, selecciona tu tienda en la barra lateral para comenzar.")
    st.image("logo_transparente.png", width=200)
else:
    try:
        logo = Image.open("logo_transparente.png")
        st.image(logo, width=180)
    except FileNotFoundError:
        st.title("GENERADOR DE COTIZACIONES")

    st.markdown("---")
    st.header("Paso 1: Cargar Catálogo de Productos")
    if 'products_df' not in st.session_state:
        st.session_state.products_df = None

    uploaded_file = st.file_uploader("📤 Selecciona el archivo CSV exportado desde Wix", type=['csv'])

    if uploaded_file:
        st.session_state.products_df = process_wix_csv(uploaded_file)

    if st.session_state.products_df is not None:
        st.success(f"✅ Catálogo cargado con {len(st.session_state.products_df)} productos.")
        st.divider()

        st.header("Paso 2: Información General")
        c1, c2, c3 = st.columns(3)
        fecha_cot = c1.date_input("Fecha", value=datetime.strptime(st.session_state.get('fecha', date.today().strftime("%d/%m/%Y")), "%d/%m/%Y"), disabled=True)
        
        st.session_state.forma_pago = c1.selectbox(
            "Forma de Pago",
            ["Transferencia bancaria (pago anticipado)", "Transferencia bancaria (50% anticipado - 50% contraentrega)", "Transferencia bancaria (contraentrega)", "Transferencia bancaria"],
            index=["Transferencia bancaria (pago anticipado)", "Transferencia bancaria (50% anticipado - 50% contraentrega)", "Transferencia bancaria (contraentrega)", "Transferencia bancaria"].index(st.session_state.forma_pago)
        )
        
        ciudad_origen = c2.text_input("Ciudad (Origen)", "BOGOTA D.C", disabled=True)
        entrega = c2.text_input("Entrega", "A CONVENIR CON EL CLIENTE", disabled=True)
        
        st.session_state.vigencia = c3.selectbox(
            "Vigencia", 
            [f"{i} DÍAS HÁBILES" for i in range(1, 8)], 
            index=[f"{i} DÍAS HÁBILES" for i in range(1, 8)].index(st.session_state.vigencia)
        )

        st.subheader("Datos del Cliente")
        cl1, cl2 = st.columns(2)
        st.session_state.cliente_nombre = cl1.text_input("Cliente:", value=st.session_state.cliente_nombre)
        st.session_state.cliente_nit = cl1.text_input("NIT/CC:", value=st.session_state.cliente_nit)
        st.session_state.cliente_ciudad = cl1.text_input("Ciudad (Destino):", value=st.session_state.cliente_ciudad)
        st.session_state.cliente_tel = cl2.text_input("Teléfono:", value=st.session_state.cliente_tel)
        st.session_state.cliente_email = cl2.text_input("Correo:", value=st.session_state.cliente_email)
        st.session_state.cliente_dir = cl2.text_input("Dirección:", value=st.session_state.cliente_dir)

        st.divider()
        st.header("Paso 3: Añadir Productos")
        form_cols = st.columns([2, 1, 1])
        sku_input = form_cols[0].text_input("Introduce el SKU del producto:")
        qty_input = form_cols[1].number_input("Cantidad", min_value=1, value=1, step=1)
        if form_cols[2].button("➕ Añadir Producto", type="primary", use_container_width=True):
            if sku_input:
                product = st.session_state.products_df[st.session_state.products_df['sku'] == sku_input]
                if not product.empty:
                    data = product.iloc[0]
                    sku = data['sku']
                    if sku in st.session_state.quote_items:
                        st.session_state.quote_items[sku]['cantidad'] += qty_input
                    else:
                        st.session_state.quote_items[sku] = {'imagen_url': data['imagen_url'], 'nombre': data['nombre'], 'sku': sku, 'cantidad': qty_input, 'precio_unitario': data['precio_iva_incluido']}
                    item = st.session_state.quote_items[sku]
                    item['valor_total'] = item['precio_unitario'] * item['cantidad']
                    if item['cantidad'] > data['inventory']:
                        st.error(f"⚠️ **Inventario bajo ({data['inventory']} unidades).** Comunicarse para revisar disponibilidad.")
                else: st.error(f"❌ SKU '{sku_input}' no encontrado.")
            else: st.warning("⚠️ Introduce un SKU.")
        
        st.divider()
        st.header("Paso 4: Cotización Actual")
        if not st.session_state.quote_items:
            st.info("Aún no has añadido productos.")
        else:
            cols = st.columns([1.2, 4, 1, 1, 2, 2, 1])
            with cols[0]: st.markdown("**Imagen**")
            with cols[1]: st.markdown("**Producto**")
            with cols[2]: st.markdown("**SKU**")
            with cols[3]: st.markdown("**Unds.**")
            with cols[4]: st.markdown("**Vlr. Unit.**")
            with cols[5]: st.markdown("**Vlr. Total**")
            
            for sku, item in list(st.session_state.quote_items.items()):
                cols = st.columns([1.2, 4, 1, 1, 2, 2, 1])
                cols[0].image(item['imagen_url'], width=70)
                cols[1].write(item['nombre'])
                cols[2].write(item['sku'])
                cols[3].write(str(item['cantidad']))
                cols[4].write(format_currency(item['precio_unitario']))
                cols[5].write(format_currency(item['valor_total']))
                cols[6].button("🗑️", key=f"delete_{sku}", on_click=remove_item, args=(sku,))
            
            st.divider()
            st.subheader("Resumen y Totales")
            subtotal = sum(item['valor_total'] for item in st.session_state.quote_items.values())
            total_unidades = sum(item['cantidad'] for item in st.session_state.quote_items.values())
            costo_flete_str, costo_flete_val = ("INCLUIDO", 0) if subtotal >= 1_000_000 else ("A convenir", 0)
            total_cotizacion = subtotal + costo_flete_val
            
            t1, t2 = st.columns(2)
            t1.metric("SUBTOTAL", format_currency(subtotal))
            t1.metric("FLETE", costo_flete_str)
            t2.metric("SUMA DE UNIDADES", str(total_unidades))
            t2.metric("TOTAL COTIZACION", format_currency(total_cotizacion))
            
            if len(st.session_state.quote_items) > 0:
                pdf_data_dict = {
                    'fecha': fecha_cot.strftime("%d/%m/%Y"),
                    'cliente_nombre': st.session_state.cliente_nombre,
                    'cliente_nit': st.session_state.cliente_nit,
                    'cliente_ciudad': st.session_state.cliente_ciudad,
                    'cliente_tel': st.session_state.cliente_tel,
                    'cliente_email': st.session_state.cliente_email,
                    'cliente_dir': st.session_state.cliente_dir,
                    'forma_pago': st.session_state.forma_pago,
                    'vigencia': st.session_state.vigencia,
                    'items': st.session_state.quote_items,
                    'subtotal': subtotal,
                    'flete_str': costo_flete_str,
                    'total_unidades': total_unidades,
                    'total_cotizacion': total_cotizacion
                }
                pdf_bytes = generate_pdf_content(pdf_data_dict)
                
                file_name_cliente = st.session_state.cliente_nombre.replace(' ', '_') if st.session_state.cliente_nombre else 'General'
                file_name_fecha = fecha_cot.strftime('%Y-%m-%d')
                
                st.download_button(
                    label="📄 Generar PDF",
                    data=pdf_bytes,
                    file_name=f"Cotizacion_{file_name_cliente}_{file_name_fecha}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
