import streamlit as st
import pandas as pd
from datetime import date, datetime
from PIL import Image
from fpdf import FPDF
import requests
from io import BytesIO
import firebase_admin
from firebase_admin import credentials, firestore, exceptions
import os
import json
from google.cloud.exceptions import NotFound
import base64

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Gestión de Cotizaciones - Jugando y Educando",
    page_icon="🧸",
    layout="wide"
)

# --- INICIALIZACIÓN DE FIREBASE ---
@st.cache_resource
def init_firebase():
    """Inicializa la conexión con Firebase de forma segura."""
    try:
        if 'firebase_secrets' in st.secrets:
            creds_dict = dict(st.secrets["firebase_secrets"])
            # Asegurar formato correcto de la clave privada
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

# --- FUNCIONES DE WIX API ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_and_process_wix_data():
    """Descarga TODOS los productos de Wix (paginados) usando Secrets."""
    
    # Verificar si existen los secrets
    if 'wix_api' not in st.secrets:
        st.error("❌ No se encontraron las credenciales de Wix en st.secrets.")
        return None

    api_key = st.secrets["wix_api"]["api_key"]
    site_id = st.secrets["wix_api"]["site_id"]
    url = "https://www.wixapis.com/stores/v1/products/query"

    headers = {
        'Authorization': api_key,
        'wix-site-id': site_id,
        'Content-Type': 'application/json'
    }
    
    products = []
    offset = 0
    limit = 100
    total_leidos = 0
    
    progress_text = "Conectando con Wix..."
    my_bar = st.progress(0, text=progress_text)

    try:
        while True:
            payload = {
                "includeHiddenProducts": True, 
                "query": {
                    "paging": {
                        "limit": limit,
                        "offset": offset
                    }
                }
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            
            if response.status_code != 200:
                st.error(f"Error comunicando con Wix: {response.status_code} - {response.text}")
                break
                
            data = response.json()
            items = data.get('products', [])
            total_results = data.get('totalResults', 0)
            
            if not items:
                break
                
            for p in items:
                sku = p.get('sku', '')
                name = p.get('name', 'Sin Nombre')
                
                # Obtener precio estándar
                price = p.get('price', {}).get('price', 0)
                
                # Inventario
                stock_info = p.get('stock', {})
                inventory = stock_info.get('quantity', 0)
                # Si es un producto "In Stock" pero sin tracking numérico, asumimos stock alto
                if inventory is None and stock_info.get('inStock', False):
                    inventory = 999 
                
                # Imagen
                image_url = "https://placehold.co/100x100/EEE/333?text=S/I"
                media = p.get('media', {})
                if media and media.get('mainMedia'):
                    full_url = media['mainMedia'].get('image', {}).get('url', '')
                    if full_url:
                        image_url = full_url

                products.append({
                    'sku': str(sku),
                    'nombre': name,
                    'precio_iva_incluido': float(price),
                    'imagen_url': image_url,
                    'inventory': int(inventory or 0)
                })

            total_leidos += len(items)
            
            if total_results > 0:
                percent = min(total_leidos / total_results, 1.0)
                my_bar.progress(percent, text=f"Descargando productos: {total_leidos} de {total_results}")

            if len(items) < limit:
                break 
            
            offset += limit
            
        my_bar.empty()
        
        if not products:
            return None

        df = pd.DataFrame(products)
        df.dropna(subset=['sku', 'nombre'], inplace=True)
        return df

    except Exception as e:
        st.error(f"Error crítico descargando datos: {str(e)}")
        my_bar.empty()
        return None

# --- FUNCIONES AUXILIARES ---
def format_currency(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "$0"
    return f"${v:,.0f}".replace(",", ".")

def parse_int_from_text(txt: str) -> int:
    if txt is None:
        return 0
    s = ''.join(ch for ch in str(txt) if ch.isdigit())
    return int(s) if s else 0

def remove_item(sku):
    if sku in st.session_state.quote_items:
        del st.session_state.quote_items[sku]

# --- CLASE PDF PERSONALIZADA ---
class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.color_primary = (4, 76, 125)
        self.color_secondary = (240, 240, 240)
        self.color_text = (50, 50, 50)
        self.color_border = (220, 220, 220)
        self.table_col_widths = None
        self.is_table_page = False
        self.current_font_family = 'Arial'

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

        if self.is_table_page and self.table_col_widths:
            self.set_y(40)
            self.draw_table_header(self.table_col_widths)

    def draw_quote_number(self, numero):
        self.set_font(self.current_font_family, '', 11)
        self.set_text_color(50, 50, 50)
        self.set_xy(150, 55)
        self.cell(35, 6, "Cotización N°:", 0, 0, 'R')

        y_numero = self.get_y()
        self.set_font(self.current_font_family, 'B', 12)
        self.set_text_color(4, 76, 125)
        self.cell(25, 6, numero, 0, 1, 'L')

        self.set_draw_color(4, 76, 125)
        self.set_line_width(0.6)
        y_line = y_numero + 10
        self.line(10, y_line, 200, y_line)
        self.ln(12)

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
        self.multi_cell(75, 6, data.get('cliente_nombre', ''), 0, 'L')
        self.set_font(self.current_font_family, "", 10)
        self.set_xy(10, self.get_y())
        self.cell(25, 6, "NIT/CC:", 0, 0, 'L')
        self.multi_cell(75, 6, data.get('cliente_nit', ''), 0, 'L')
        self.set_xy(10, self.get_y())
        self.cell(25, 6, "Dirección:", 0, 0, 'L')
        self.multi_cell(75, 6, f"{data.get('cliente_dir','')}, {data.get('cliente_ciudad','')}", 0, 'L')
        y_left_end = self.get_y()
        self.set_xy(110, y_start)
        self.cell(25, 6, "Fecha:", 0, 0, 'L')
        self.multi_cell(75, 6, data.get('fecha', ''), 0, 'L')
        self.set_xy(110, self.get_y())
        self.cell(25, 6, "Teléfono:", 0, 0, 'L')
        self.multi_cell(75, 6, data.get('cliente_tel', ''), 0, 'L')
        self.set_xy(110, self.get_y())
        self.cell(25, 6, "Vigencia:", 0, 0, 'L')
        self.multi_cell(75, 6, data.get('vigencia', ''), 0, 'L')
        y_right_end = self.get_y()
        self.set_y(max(y_left_end, y_right_end) + 5)

    def get_multicell_lines(self, text, width):
        self.set_font(self.current_font_family, "", 9)
        words = str(text).split(' ')
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

    def ensure_row_fits(self, row_height):
        if self.get_y() + row_height > self.page_break_trigger:
            self.add_page()
            if self.is_table_page and self.table_col_widths:
                self.set_y(40)
                self.draw_table_header(self.table_col_widths)

    def draw_table_row(self, item, col_widths, fill=False):
        line_height = 5
        num_lines = self.get_multicell_lines(item.get('nombre', ''), col_widths['name'] - 2)
        name_height = num_lines * line_height
        row_height = max(30, name_height + 4)

        self.ensure_row_fits(row_height)

        x_start = self.get_x()
        y_start = self.get_y()

        self.set_font(self.current_font_family, "", 9)
        self.set_text_color(*self.color_text)
        self.set_draw_color(*self.color_border)
        self.set_fill_color(*self.color_secondary)

        self.cell(col_widths['img'], row_height, "", 'B', 0, 'C', fill)
        self.cell(col_widths['name'], row_height, "", 'B', 0, 'C', fill)
        self.cell(col_widths['sku'], row_height, "", 'B', 0, 'C', fill)
        self.cell(col_widths['qty'], row_height, "", 'B', 0, 'C', fill)
        self.cell(col_widths['price'], row_height, "", 'B', 0, 'R', fill)
        self.cell(col_widths['total'], row_height, "", 'B', 1, 'R', fill)

        # Imagen
        try:
            image_source = None
            if item.get('imagen_base64'):
                image_bytes = base64.b64decode(item['imagen_base64'])
                image_source = BytesIO(image_bytes)
            elif item.get('imagen_url') and "placehold.co" not in item.get('imagen_url'):
                # Añadimos header para simular navegador si es necesario, 
                # aunque Wix suele servir imágenes estáticas sin problemas
                headers_img = {'User-Agent': 'Mozilla/5.0'}
                response = requests.get(item['imagen_url'], headers=headers_img, timeout=5)
                if response.status_code == 200:
                    image_source = BytesIO(response.content)
            
            if image_source:
                # Ajuste de imagen para mantener proporción
                self.image(image_source, x=x_start + 2, y=y_start + 2, w=col_widths['img'] - 4, h=row_height - 4)
            else:
                raise Exception("No image")
        except Exception:
            v_offset_placeholder = (row_height - 4) / 2
            self.set_xy(x_start, y_start + v_offset_placeholder)
            self.cell(col_widths['img'], 4, "S/I", 0, 0, 'C')

        # Nombre
        name_v_offset = (row_height - name_height) / 2
        self.set_xy(x_start + col_widths['img'], y_start + name_v_offset)
        self.multi_cell(col_widths['name'], line_height, str(item.get('nombre', '')), border=0, align='C')

        text_height = self.font_size
        cell_v_offset = (row_height - text_height) / 2
        
        # SKU
        self.set_xy(x_start + col_widths['img'] + col_widths['name'], y_start + cell_v_offset)
        self.cell(col_widths['sku'], text_height, str(item.get('sku', '')), 0, 0, 'C')
        
        # Cantidad
        self.set_x(x_start + col_widths['img'] + col_widths['name'] + col_widths['sku'])
        self.cell(col_widths['qty'], text_height, str(item.get('cantidad', '')), 0, 0, 'C')
        
        # Precio
        self.set_x(x_start + col_widths['img'] + col_widths['name'] + col_widths['sku'] + col_widths['qty'])
        self.cell(col_widths['price'], text_height, format_currency(item.get('precio_unitario', 0)), 0, 0, 'R')
        
        # Total
        self.set_x(x_start + col_widths['img'] + col_widths['name'] + col_widths['sku'] + col_widths['qty'] + col_widths['price'])
        self.cell(col_widths['total'], text_height, format_currency(item.get('valor_total', 0)), 0, 0, 'R')

        self.set_y(y_start + row_height)

    def footer(self):
        self.set_y(-15)
        self.set_font(self.current_font_family, "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Página {self.page_no()}", 0, 0, 'C')

# --- FUNCIONES DE FIREBASE (DB) ---
@firestore.transactional
def get_next_quote_number_transaction(transaction, counter_ref, tienda_key):
    snapshot = counter_ref.get(transaction=transaction)
    data = snapshot.to_dict() or {}
    current_number = data.get(tienda_key, 0)
    new_number = current_number + 1
    transaction.set(counter_ref, {tienda_key: new_number}, merge=True)
    return new_number

def get_next_quote_number(db, tienda):
    if not db: return None
    tienda_key = tienda.lower()
    counter_ref = db.collection('counters').document('cotizaciones')
    
    try:
        new_number = get_next_quote_number_transaction(db.transaction(), counter_ref, tienda_key)
        prefix = "OV" if tienda == "Oviedo" else "BQ"
        return f"{prefix}-{str(new_number).zfill(4)}"
    except Exception as e:
        st.error(f"Error al obtener número de cotización: {e}")
        return None

def get_quotes_list(db, tienda):
    if not db or not tienda: return {}
    quotes_ref = db.collection('cotizaciones').where('tienda', '==', tienda).stream()
    quotes_dict = {}
    for quote in quotes_ref:
        quote_data = quote.to_dict()
        label = quote_data.get('numero_cotizacion', quote.id)
        quotes_dict[f"{label} - {quote_data.get('cliente_nombre', 'N/A')}"] = quote.id
    return quotes_dict

def save_quote(db, quote_data, quote_id=None):
    if not db:
        st.error("Conexión a la base de datos no disponible.")
        return None
    if 'tienda' not in quote_data or not quote_data['tienda']:
        st.error("Error: No se puede guardar la cotización sin una tienda asignada.")
        return None
    try:
        if quote_id:
            db.collection('cotizaciones').document(quote_id).update(quote_data)
            st.success(f"¡Cotización '{quote_data.get('numero_cotizacion', '')}' actualizada!")
        else:
            quote_number = get_next_quote_number(db, quote_data['tienda'])
            if not quote_number: return None
            
            quote_data['numero_cotizacion'] = quote_number
            quote_data['estado'] = "🔵 Creada"
            quote_data['comentarios'] = ""

            db.collection('cotizaciones').add(quote_data)
            st.success(f"¡Cotización '{quote_number}' guardada como nueva!")
        
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Error al guardar la cotización: {e}")
        return None

def delete_quote(db, quote_id):
    if not db: return
    try:
        db.collection('cotizaciones').document(quote_id).delete()
        st.success("¡Cotización eliminada con éxito!")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error al eliminar la cotización: {e}")

def get_all_quotes_for_tracking(db, tienda):
    if not db or not tienda: return []
    quotes_ref = db.collection('cotizaciones').where('tienda', '==', tienda).stream()
    quotes_list = []
    for quote in quotes_ref:
        data = quote.to_dict()
        subtotal = sum(item.get('valor_total', 0) for item in data.get('items', {}).values())
        flete_val_doc = data.get('flete_val', 0)
        quotes_list.append({
            "id": quote.id,
            "N° Cotización": data.get("numero_cotizacion", "S/N"),
            "Fecha": data.get("fecha", "S/F"),
            "Cliente": data.get("cliente_nombre", "N/A"),
            "Total": subtotal + (flete_val_doc or 0),
            "Estado": data.get("estado", "🔵 Creada"),
            "Comentarios": data.get("comentarios", "")
        })
    return quotes_list

def update_quotes_tracking(db, edited_data):
    if not db: return
    try:
        for doc_id, changes in edited_data.items():
            db.collection('cotizaciones').document(doc_id).update(changes)
        st.success("¡Seguimiento actualizado con éxito!")
    except Exception as e:
        st.error(f"Error al actualizar seguimiento: {e}")

# --- GENERACIÓN DEL PDF ---
def generate_pdf_content(quote_data):
    pdf = PDF('P', 'mm', 'A4')
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    pdf.set_font(pdf.current_font_family, "B", 22)
    pdf.set_text_color(*pdf.color_primary)
    pdf.set_y(45)
    pdf.cell(130, 10, "COTIZACIÓN", 0, 0, 'L')
    pdf.draw_quote_number(quote_data.get("numero_cotizacion", "S/N"))
    pdf.draw_client_info(quote_data)
    
    col_widths = {'img': 30, 'name': 70, 'sku': 20, 'qty': 15, 'price': 25, 'total': 30}
    
    pdf.is_table_page = True
    pdf.table_col_widths = col_widths
    pdf.draw_table_header(col_widths)
    
    fill = True
    for item in quote_data['items'].values():
        pdf.draw_table_row(item, col_widths, fill)
        fill = not fill
    
    pdf.is_table_page = False

    needed = 55
    if pdf.get_y() + needed > pdf.page_break_trigger:
        pdf.add_page()

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
    flete_label = "FLETE (INCLUIDO)" if str(quote_data.get('flete_str','')).upper() == 'INCLUIDO' else "FLETE"
    pdf.cell(70, 8, flete_label, 0, 0, 'R')
    pdf.set_font(pdf.current_font_family, "B", 10)
    pdf.cell(30, 8, format_currency(quote_data.get('flete_val', 0)), 0, 1, 'R')

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

# --- ESTADO DE SESIÓN ---
def init_session_state():
    defaults = {
        'tienda_seleccionada': None, 'quote_items': {}, 'current_quote_id': None,
        'cliente_nombre': "", 'cliente_nit': "", 'cliente_ciudad': "",
        'cliente_tel': "", 'cliente_email': "", 'cliente_dir': "",
        'forma_pago': "Transferencia bancaria (pago anticipado)", 'vigencia': "5 DÍAS HÁBILES",
        'numero_cotizacion': None, 'estado': None, 'comentarios': None,
        'fecha': datetime.now(),
        'manual_product_count': 0,
        'flete_val': 0
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

def clear_form_state():
    current_tienda = st.session_state.tienda_seleccionada
    products_df = st.session_state.get('products_df')
    
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    
    init_session_state()
    st.session_state.tienda_seleccionada = current_tienda
    st.session_state.products_df = products_df
    st.success("Formulario limpiado. Listo para una nueva cotización.")

init_session_state()

# --- BARRA LATERAL ---
with st.sidebar:
    st.title("Gestión de Cotizaciones")
    tiendas = ["Oviedo", "Barranquilla"]
    
    def on_store_change():
        new_store = st.session_state.tienda_selector
        products_df = st.session_state.get('products_df')

        for key in list(st.session_state.keys()):
            del st.session_state[key]
        
        init_session_state()
        st.session_state.tienda_seleccionada = new_store
        st.session_state.products_df = products_df

    if 'tienda_seleccionada' not in st.session_state or st.session_state.tienda_seleccionada is None:
        st.session_state.tienda_seleccionada = tiendas[0]

    st.radio(
        "Selecciona tu tienda:",
        tiendas,
        key="tienda_selector",
        on_change=on_store_change,
        horizontal=True,
        index=tiendas.index(st.session_state.tienda_seleccionada)
    )

    if st.session_state.tienda_seleccionada:
        st.success(f"Tienda seleccionada: **{st.session_state.tienda_seleccionada}**")

# --- UI PRINCIPAL ---
if not st.session_state.tienda_seleccionada:
    st.info("👋 ¡Bienvenido! Por favor, selecciona tu tienda en la barra lateral para comenzar.")
    try:
        st.image("logo_transparente.png", width=200)
    except FileNotFoundError:
        pass
else:
    tab1, tab2 = st.tabs(["📝 Crear Cotización", "📊 Seguimiento de Cotizaciones"])

    # --- PESTAÑA DE CREAR COTIZACIÓN ---
    with tab1:
        with st.sidebar:
            st.divider()
            st.header("Opciones de Creación")
            if st.button("➕ Nueva Cotización", use_container_width=True):
                clear_form_state()
                st.rerun()

            st.divider()
            
            if db:
                quotes_dict = get_quotes_list(db, st.session_state.tienda_seleccionada)
                if quotes_dict:
                    selected_quote_label = st.selectbox(
                        "Cargar Cotización Existente",
                        options=list(quotes_dict.keys()),
                        index=None,
                        placeholder="Selecciona una cotización...",
                        key="load_quote_sb"
                    )

                    if st.button("📥 Cargar Cotización", use_container_width=True):
                        if selected_quote_label:
                            quote_id_to_load = quotes_dict[selected_quote_label]
                            quote_data = db.collection('cotizaciones').document(quote_id_to_load).get().to_dict()
                            
                            clear_form_state()
                            
                            st.session_state.current_quote_id = quote_id_to_load
                            st.session_state.cliente_nombre = quote_data.get('cliente_nombre', '')
                            st.session_state.cliente_nit = quote_data.get('cliente_nit', '')
                            st.session_state.cliente_ciudad = quote_data.get('cliente_ciudad', '')
                            st.session_state.cliente_tel = quote_data.get('cliente_tel', '')
                            st.session_state.cliente_email = quote_data.get('cliente_email', '')
                            st.session_state.cliente_dir = quote_data.get('cliente_dir', '')
                            st.session_state.forma_pago = quote_data.get('forma_pago', "Transferencia bancaria (pago anticipado)")
                            st.session_state.vigencia = quote_data.get('vigencia', "5 DÍAS HÁBILES")
                            st.session_state.numero_cotizacion = quote_data.get('numero_cotizacion')
                            st.session_state.estado = quote_data.get('estado')
                            st.session_state.comentarios = quote_data.get('comentarios')
                            st.session_state.quote_items = quote_data.get('items', {})
                            st.session_state.flete_val = quote_data.get('flete_val', 0)

                            fecha_str = quote_data.get('fecha')
                            if fecha_str and isinstance(fecha_str, str):
                                st.session_state.fecha = datetime.strptime(fecha_str, "%d/%m/%Y")
                            
                            st.success(f"Cotización '{st.session_state.numero_cotizacion}' cargada.")
                            st.rerun()

            st.divider()
            
            if st.session_state.get('current_quote_id'):
                if st.button("🗑️ Eliminar Cotización", use_container_width=True):
                    delete_quote(db, st.session_state.current_quote_id)
                    clear_form_state()
                    st.rerun()

        try:
            logo = Image.open("logo_transparente.png")
            st.image(logo, width=180)
        except FileNotFoundError:
            st.title("GENERADOR DE COTIZACIONES")

        st.markdown("---")
        st.header("Paso 1: Catálogo de Productos (Sincronizado)")
        
        col_cat_1, col_cat_2 = st.columns([3, 1])
        with col_cat_1:
            st.info("El catálogo se conecta directamente a Wix y trae TODOS los productos (incluyendo stock 0).")
        with col_cat_2:
            if st.button("🔄 Forzar Actualización", help="Vuelve a descargar los productos desde Wix"):
                st.cache_data.clear()
                st.rerun()

        # Cargar datos automáticamente si no existen
        if st.session_state.get('products_df') is None:
            df_wix = fetch_and_process_wix_data()
            if df_wix is not None:
                st.session_state.products_df = df_wix
            else:
                st.warning("⚠️ No se pudieron cargar los productos. Revisa tu conexión o API Key.")

        # Mostrar confirmación si ya están cargados
        if st.session_state.get('products_df') is not None:
            st.success(f"✅ Catálogo sincronizado: {len(st.session_state.products_df)} productos disponibles.")
            
            # Buscador rápido para verificar
            with st.expander("🔍 Verificar productos (Buscador rápido)"):
                search_term = st.text_input("Buscar por nombre o SKU en el catálogo cargado:")
                if search_term:
                    mask = st.session_state.products_df.apply(lambda x: search_term.lower() in str(x).lower(), axis=1)
                    st.dataframe(st.session_state.products_df[mask].head(10))
                else:
                    st.dataframe(st.session_state.products_df.head())
            st.divider()

            st.header("Paso 2: Información General")
            c1, c2, c3 = st.columns(3)
            c1.date_input("Fecha", key="fecha", disabled=True)
            c1.text_input("Ciudad (Origen)", "BOGOTA D.C", disabled=True)
            c2.text_input("Entrega", "A CONVENIR CON EL CLIENTE", disabled=True)
            c2.selectbox("Forma de Pago", ["Transferencia bancaria (pago anticipado)", "50% anticipado - 50% contraentrega", "Contraentrega"], key="forma_pago")
            c3.selectbox("Vigencia", [f"{i} DÍAS HÁBILES" for i in range(1, 8)], key="vigencia")

            st.subheader("Datos del Cliente")
            cl1, cl2 = st.columns(2)
            cl1.text_input("Cliente:", key="cliente_nombre")
            cl1.text_input("NIT/CC:", key="cliente_nit")
            cl1.text_input("Ciudad (Destino):", key="cliente_ciudad")
            cl2.text_input("Teléfono:", key="cliente_tel")
            cl2.text_input("Correo:", key="cliente_email")
            cl2.text_input("Dirección:", key="cliente_dir")

            st.divider()
            st.header("Paso 3: Añadir Productos")
            form_cols = st.columns([2, 1, 1])
            sku_input = form_cols[0].text_input("Introduce el SKU del producto:", key="sku_input")
            qty_input = form_cols[1].number_input("Cantidad", min_value=1, value=1, step=1, key="qty_input")
            if form_cols[2].button("➕ Añadir Producto", type="primary", use_container_width=True):
                if st.session_state.sku_input:
                    product = st.session_state.products_df[st.session_state.products_df['sku'] == st.session_state.sku_input]
                    if not product.empty:
                        data = product.iloc[0]
                        sku = data['sku']
                        if sku in st.session_state.quote_items:
                            st.session_state.quote_items[sku]['cantidad'] += st.session_state.qty_input
                        else:
                            st.session_state.quote_items[sku] = {
                                'imagen_url': data['imagen_url'],
                                'nombre': data['nombre'],
                                'sku': sku,
                                'cantidad': st.session_state.qty_input,
                                'precio_unitario': data['precio_iva_incluido']
                            }
                        item = st.session_state.quote_items[sku]
                        item['valor_total'] = item['precio_unitario'] * item['cantidad']
                        st.rerun()
                    else:
                        st.error(f"❌ SKU '{st.session_state.sku_input}' no encontrado.")
                else:
                    st.warning("⚠️ Introduce un SKU.")
            
            with st.expander("👇 O añadir un producto manualmente"):
                with st.form("manual_product_form", clear_on_submit=True):
                    manual_name = st.text_input("Nombre del Producto")
                    manual_sku = st.text_input("Código/SKU (ej: VARIOS-01)")
                    manual_price = st.number_input("Valor Unitario", min_value=0, step=100)
                    manual_qty = st.number_input("Cantidad", min_value=1, value=1, step=1)
                    manual_image = st.file_uploader("Subir Imagen (Opcional)", type=['png', 'jpg', 'jpeg'])
                    
                    submitted = st.form_submit_button("Añadir Producto Manualmente")
                    if submitted:
                        if not all([manual_name, manual_sku, manual_price, manual_qty]):
                            st.warning("Por favor, completa todos los campos del producto manual.")
                        else:
                            st.session_state.manual_product_count += 1
                            unique_sku = f"manual_{st.session_state.manual_product_count}"
                            
                            image_base64 = None
                            if manual_image is not None:
                                image_bytes = manual_image.getvalue()
                                image_base64 = base64.b64encode(image_bytes).decode()

                            st.session_state.quote_items[unique_sku] = {
                                'nombre': manual_name,
                                'sku': manual_sku,
                                'cantidad': manual_qty,
                                'precio_unitario': manual_price,
                                'valor_total': manual_price * manual_qty,
                                'imagen_base64': image_base64,
                                'imagen_url': None
                            }
                            st.success(f"Producto '{manual_name}' añadido.")
                            st.rerun()

            st.divider()
            st.header("Paso 4: Cotización Actual")
            if not st.session_state.quote_items:
                st.info("Aún no has añadido productos.")
            else:
                cols = st.columns([1.2, 4, 1, 1, 2, 2, 1])
                headers = ["Imagen", "Producto", "SKU", "Unds.", "Vlr. Unit.", "Vlr. Total", ""]
                for col, header in zip(cols, headers):
                    col.markdown(f"**{header}**")
                
                for sku, item in list(st.session_state.quote_items.items()):
                    cols = st.columns([1.2, 4, 1, 1, 2, 2, 1])
                    if item.get('imagen_base64'):
                        img_bytes = base64.b64decode(item['imagen_base64'])
                        cols[0].image(img_bytes, width=70)
                    elif item.get('imagen_url') and "placehold.co" not in item['imagen_url']:
                        cols[0].image(item['imagen_url'], width=70)
                    else:
                        cols[0].markdown("S/I")

                    cols[1].write(item['nombre'])
                    cols[2].write(item['sku'])
                    cols[3].write(str(item['cantidad']))
                    cols[4].write(format_currency(item['precio_unitario']))
                    cols[5].write(format_currency(item['valor_total']))
                    if cols[6].button("🗑️", key=f"delete_{sku}", on_click=remove_item, args=(sku,)):
                        st.rerun()
                
                st.divider()
                st.subheader("Resumen y Acciones")
                subtotal = sum(item['valor_total'] for item in st.session_state.quote_items.values())
                total_unidades = sum(item['cantidad'] for item in st.session_state.quote_items.values())

                st.subheader("Costo de Envío (Flete)")
                
                opcion_flete = st.radio(
                    "Elige una opción para el flete:",
                    ("Ingresar valor manualmente", "Flete Incluido en el precio"),
                    key="flete_option",
                    horizontal=True
                )

                costo_flete_str = "" 

                if opcion_flete == "Ingresar valor manualmente":
                    costo_flete_str = "MANUAL"
                    flete_text = st.text_input(
                        "Valor del Flete",
                        value=str(st.session_state.get('flete_val', 0)),
                        help="Escribe solo números. Ej: 35000"
                    )
                    st.session_state.flete_val = parse_int_from_text(flete_text)
                else:
                    costo_flete_str = "INCLUIDO"
                    st.session_state.flete_val = 0
                
                total_cotizacion = subtotal + (st.session_state.flete_val or 0)
                
                t1, t2, t3 = st.columns(3)
                t1.metric("SUBTOTAL", format_currency(subtotal))
                
                flete_display_val = "INCLUIDO" if opcion_flete == "Flete Incluido en el precio" else format_currency(st.session_state.flete_val)
                t2.metric("FLETE", flete_display_val)
                
                t3.metric("TOTAL COTIZACION", format_currency(total_cotizacion))

                st.caption(f"Total de unidades: {total_unidades}")
                
                action_cols = st.columns(2)
                
                is_new_quote = not st.session_state.current_quote_id
                save_button_label = "💾 Guardar como Nueva" if is_new_quote else "💾 Guardar Cambios"
                if action_cols[0].button(save_button_label, use_container_width=True, type="primary"):
                    if not st.session_state.cliente_nombre:
                        st.warning("Por favor, introduce al menos el nombre del cliente.")
                    else:
                        quote_data_to_save = {
                            'tienda': st.session_state.tienda_seleccionada,
                            'fecha': st.session_state.fecha.strftime("%d/%m/%Y"),
                            'cliente_nombre': st.session_state.cliente_nombre,
                            'cliente_nit': st.session_state.cliente_nit,
                            'cliente_ciudad': st.session_state.cliente_ciudad,
                            'cliente_tel': st.session_state.cliente_tel,
                            'cliente_email': st.session_state.cliente_email,
                            'cliente_dir': st.session_state.cliente_dir,
                            'forma_pago': st.session_state.forma_pago,
                            'vigencia': st.session_state.vigencia,
                            'items': st.session_state.quote_items,
                            'numero_cotizacion': st.session_state.numero_cotizacion,
                            'estado': st.session_state.estado,
                            'comentarios': st.session_state.comentarios,
                            'flete_val': int(st.session_state.flete_val)
                        }
                        if save_quote(db, quote_data_to_save, st.session_state.current_quote_id):
                            if is_new_quote:
                                clear_form_state()
                                st.rerun()

                pdf_data_dict = {
                    'fecha': st.session_state.fecha.strftime("%d/%m/%Y"),
                    'numero_cotizacion': st.session_state.numero_cotizacion or "N/A",
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
                    'flete_val': int(st.session_state.flete_val),
                    'total_unidades': total_unidades,
                    'total_cotizacion': total_cotizacion
                }
                pdf_bytes = generate_pdf_content(pdf_data_dict)
                
                file_name_cliente = st.session_state.cliente_nombre.replace(' ', '_') if st.session_state.cliente_nombre else 'General'
                file_name_cot = st.session_state.numero_cotizacion or "NUEVA"
                
                action_cols[1].download_button(
                    label="📄 Generar PDF",
                    data=pdf_bytes,
                    file_name=f"Cotizacion_{file_name_cot}_{file_name_cliente}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

    # --- PESTAÑA DE SEGUIMIENTO ---
    with tab2:
        st.header(f"Seguimiento de Cotizaciones - {st.session_state.tienda_seleccionada}")

        if db:
            tracking_data = get_all_quotes_for_tracking(db, st.session_state.tienda_seleccionada)
            if not tracking_data:
                st.info("No hay cotizaciones para mostrar en esta tienda.")
            else:
                df = pd.DataFrame(tracking_data)
                
                if 'original_df' not in st.session_state:
                    st.session_state.original_df = df.set_index('id').copy()

                st.info("Puedes editar los campos 'Estado' y 'Comentarios' directamente en la tabla. Luego presiona 'Guardar Cambios'.")
                
                edited_df = st.data_editor(
                    df,
                    column_config={
                        "id": None,
                        "N° Cotización": st.column_config.TextColumn(disabled=True),
                        "Fecha": st.column_config.TextColumn(disabled=True),
                        "Cliente": st.column_config.TextColumn(disabled=True),
                        "Total": st.column_config.NumberColumn("Total", format="$ %d", disabled=True),
                        "Estado": st.column_config.SelectboxColumn(
                            "Estado",
                            options=["🔵 Creada", "✉️ Enviada", "✅ Aprobada", "❌ Rechazada", "🧾 Facturada"],
                            required=True,
                        ),
                        "Comentarios": st.column_config.TextColumn(width="large")
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="tracking_editor"
                )

                if st.button("💾 Guardar Cambios de Seguimiento", type="primary"):
                    changes_to_update = {}
                    original_df_reindexed = st.session_state.original_df.reset_index()

                    for i, row in edited_df.iterrows():
                        try:
                            original_row = original_df_reindexed.iloc[i]
                            doc_id = original_row['id']
                            
                            if row['Estado'] != original_row['Estado'] or row['Comentarios'] != original_row['Comentarios']:
                                changes_to_update[doc_id] = {
                                    'estado': row['Estado'],
                                    'comentarios': row['Comentarios']
                                }
                        except IndexError:
                            continue
                    
                    if changes_to_update:
                        update_quotes_tracking(db, changes_to_update)
                        st.cache_data.clear()
                        if 'original_df' in st.session_state:
                            del st.session_state.original_df
                        st.rerun()
                    else:
                        st.toast("No se detectaron cambios para guardar.")
