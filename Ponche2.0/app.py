import os
import sys
import io

# Solución para evitar errores de carga de Intel oneMKL con Pandas/NumPy en Windows
os.environ['OMP_NUM_THREADS'] = '1'
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo # <- Importante para manejar la zona horaria exacta
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.utils import secure_filename
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart

app = Flask(__name__)
app.secret_key = 'clave_secreta_super_segura'

# Zona horaria oficial para República Dominicana
TIMEZONE_RD = ZoneInfo("America/Santo_Domingo")

def obtener_ahora_rd():
    """Retorna la fecha y hora actual ajustada a la República Dominicana."""
    return datetime.now(TIMEZONE_RD).replace(tzinfo=None)

# Configuración de ruta absoluta compatible con PyInstaller (.exe) y desarrollo
if getattr(sys, 'frozen', False):
    basedir = os.path.dirname(sys.executable)
else:
    basedir = os.path.abspath(os.path.dirname(__file__))

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'asistencia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db = SQLAlchemy(app)

# --- MODELOS DE BASE DE DATOS ---
class Empleado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    foto = db.Column(db.String(200), nullable=True, default='default.png')

class Asistencia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    empleado_id = db.Column(db.Integer, db.ForeignKey('empleado.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=obtener_ahora_rd) # Usa hora RD por defecto
    tipo = db.Column(db.String(20), nullable=False)  # "ENTRADA" o "SALIDA"

class Configuracion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(50), unique=True, nullable=False)
    valor = db.Column(db.String(200), nullable=False)

with app.app_context():
    db.create_all()
    admin_config = Configuracion.query.filter_by(clave='admin_password').first()
    if not admin_config:
        db.session.add(Configuracion(clave='admin_password', valor='admin'))
        db.session.commit()

# --- CLASE AUXILIAR PARA PIE DE PÁGINA PROFESIONAL (PDF) ---
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor('#777777'))
        self.setStrokeColor(colors.HexColor('#cccccc'))
        self.setLineWidth(0.5)
        self.line(30, 40, letter[0] - 30, 40)
        
        self.drawString(30, 28, "Sistema de Control de Asistencia - República Dominicana")
        self.drawRightString(letter[0] - 30, 28, f"Página {self._pageNumber} de {page_count}")
        self.restoreState()


# --- RUTAS DE VISTAS (HTML) ---

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    password = data.get('password')
    admin_config = Configuracion.query.filter_by(clave='admin_password').first()
    if admin_config and admin_config.valor == password:
        session['is_admin'] = True
        return jsonify({"mensaje": "Acceso concedido"})
    return jsonify({"error": "Contraseña incorrecta."}), 401


@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('home'))


@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        return redirect(url_for('home'))
        
    with app.app_context():
        empleados = Empleado.query.all()
        hoy_inicio = obtener_ahora_rd().replace(hour=0, minute=0, second=0, microsecond=0)
        
        activos = []
        for emp in empleados:
            ultimo = Asistencia.query.filter(
                Asistencia.empleado_id == emp.id,
                Asistencia.timestamp >= hoy_inicio
            ).order_by(Asistencia.timestamp.desc()).first()
            
            if ultimo and ultimo.tipo == "ENTRADA":
                activos.append({
                    "id": emp.id,
                    "nombre": emp.nombre,
                    "codigo": emp.codigo,
                    # Formato 12 horas con AM/PM adaptado a RD (ej: 08:30:15 a. m.) o formato 24h limpio
                    "hora_llegada": ultimo.timestamp.strftime("%I:%M:%S %p")
                })

        historial_raw = Asistencia.query.join(Empleado).add_columns(
            Empleado.nombre, Empleado.codigo, Asistencia.timestamp, Asistencia.tipo
        ).order_by(Asistencia.timestamp.desc()).limit(50).all()
        
        historial = [{
            "nombre": h.nombre,
            "codigo": h.codigo,
            # Formato de fecha dominicana estándar: DD/MM/YYYY HH:MM:SS
            "fecha_hora": h.timestamp.strftime("%d/%m/%Y %I:%M:%S %p"),
            "tipo": h.tipo
        } for h in historial_raw]

        asistencias_todas = Asistencia.query.order_by(Asistencia.timestamp).all()
        sesiones_por_dia = {}
        for reg in asistencias_todas:
            fecha_str = reg.timestamp.strftime("%d/%m/%Y")
            clave = (reg.empleado_id, fecha_str)
            if clave not in sesiones_por_dia:
                sesiones_por_dia[clave] = {"entrada": None, "salida": None}
            if reg.tipo == "ENTRADA" and not sesiones_por_dia[clave]["entrada"]:
                sesiones_por_dia[clave]["entrada"] = reg.timestamp
            elif reg.tipo == "SALIDA":
                sesiones_por_dia[clave]["salida"] = reg.timestamp

        total_horas = 0
        total_jornadas = 0
        for clave, tiempos in sesiones_por_dia.items():
            if tiempos["entrada"] and tiempos["salida"]:
                duracion = (tiempos["salida"] - tiempos["entrada"]).total_seconds() / 3600
                if 0 < duracion < 16:
                    total_horas += duracion
                    total_jornadas += 1

        promedio_horas = round(total_horas / total_jornadas, 2) if total_jornadas > 0 else 0
        lista_empleados = [{"id": e.id, "codigo": e.codigo, "nombre": e.nombre} for e in empleados]

    return render_template('admin.html', 
                           activos=activos, 
                           historial=historial, 
                           total_empleados=len(empleados),
                           promedio_horas=promedio_horas,
                           empleados=lista_empleados)


@app.route('/admin/empleado/nuevo')
def nuevo_empleado_page():
    if not session.get('is_admin'):
        return redirect(url_for('home'))
    return render_template('nuevo_empleado.html')


@app.route('/admin/empleado/<int:empleado_id>')
def empleado_detalle(empleado_id):
    if not session.get('is_admin'):
        return redirect(url_for('home'))
        
    empleado = Empleado.query.get_or_404(empleado_id)
    
    offset = request.args.get('offset', 0, type=int)
    hoy = obtener_ahora_rd().replace(hour=0, minute=0, second=0, microsecond=0)
    fin_periodo = hoy - timedelta(days=offset * 7)
    inicio_periodo = fin_periodo - timedelta(days=6)
    
    asistencias = Asistencia.query.filter_by(empleado_id=empleado.id).order_by(Asistencia.timestamp).all()
    
    sesiones_por_dia = {}
    for reg in asistencias:
        fecha_str = reg.timestamp.strftime("%d/%m/%Y")
        if fecha_str not in sesiones_por_dia:
            sesiones_por_dia[fecha_str] = {"entrada": None, "salida": None}
        if reg.tipo == "ENTRADA" and not sesiones_por_dia[fecha_str]["entrada"]:
            sesiones_por_dia[fecha_str]["entrada"] = reg.timestamp
        elif reg.tipo == "SALIDA":
            sesiones_por_dia[fecha_str]["salida"] = reg.timestamp
            
    total_horas_emp = 0
    jornadas_emp = 0
    horas_por_dia_map = {}
    
    for fecha_str, tiempos in sesiones_por_dia.items():
        if tiempos["entrada"] and tiempos["salida"]:
            duracion = (tiempos["salida"] - tiempos["entrada"]).total_seconds() / 3600
            if 0 < duracion < 16:
                total_horas_emp += duracion
                jornadas_emp += 1
                horas_por_dia_map[fecha_str] = round(duracion, 2)
                
    promedio_empleado = round(total_horas_emp / jornadas_emp, 2) if jornadas_emp > 0 else 0
    
    dias_grafico = []
    horas_grafico = []
    
    current_d = inicio_periodo
    while current_d <= fin_periodo:
        f_str = current_d.strftime("%d/%m/%Y")
        dias_grafico.append(current_d.strftime("%d/%m"))
        horas_grafico.append(horas_por_dia_map.get(f_str, 0))
        current_d += timedelta(days=1)

    return render_template('empleado_detalle.html',
                           empleado=empleado,
                           promedio_empleado=promedio_empleado,
                           dias_grafico=dias_grafico,
                           horas_grafico=horas_grafico,
                           offset=offset)


@app.route('/admin/empleado/<int:empleado_id>/pdf')
def descargar_pdf_empleado(empleado_id):
    if not session.get('is_admin'):
        return redirect(url_for('home'))
        
    empleado = Empleado.query.get_or_404(empleado_id)
    asistencias = Asistencia.query.filter_by(empleado_id=empleado.id).order_by(Asistencia.timestamp).all()
    
    sesiones_por_dia = {}
    for reg in asistencias:
        fecha_str = reg.timestamp.strftime("%d/%m/%Y")
        if fecha_str not in sesiones_por_dia:
            sesiones_por_dia[fecha_str] = {"entrada": None, "salida": None}
        if reg.tipo == "ENTRADA" and not sesiones_por_dia[fecha_str]["entrada"]:
            sesiones_por_dia[fecha_str]["entrada"] = reg.timestamp
        elif reg.tipo == "SALIDA":
            sesiones_por_dia[fecha_str]["salida"] = reg.timestamp
            
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=40, bottomMargin=50)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#111827'), fontName='Helvetica-Bold', spaceAfter=4)
    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#4b5563'), fontName='Helvetica', spaceAfter=15)
    
    elements.append(Paragraph(f"Reporte de Asistencia: <b>{empleado.nombre}</b>", title_style))
    elements.append(Paragraph(f"Código: <b>{empleado.codigo}</b> &nbsp;|&nbsp; Generado el: {obtener_ahora_rd().strftime('%d/%m/%Y %I:%M %p')}", subtitle_style))
    elements.append(Spacer(1, 5))
    
    table_data = [["Fecha", "Hora Entrada", "Hora Salida", "Total Horas"]]
    total_horas_emp = 0
    jornadas_emp = 0
    
    for fecha_str, tiempos in sorted(sesiones_por_dia.items(), reverse=True):
        entrada_str = tiempos["entrada"].strftime("%I:%M:%S %p") if tiempos["entrada"] else "Sin registro"
        salida_str = tiempos["salida"].strftime("%I:%M:%S %p") if tiempos["salida"] else "Pendiente"
        
        duracion_str = "-"
        if tiempos["entrada"] and tiempos["salida"]:
            duracion = (tiempos["salida"] - tiempos["entrada"]).total_seconds() / 3600
            if 0 < duracion < 16:
                total_horas_emp += duracion
                jornadas_emp += 1
                duracion_str = f"{round(duracion, 2)} hrs"
        
        table_data.append([fecha_str, entrada_str, salida_str, duracion_str])
        
    promedio_empleado = round(total_horas_emp / jornadas_emp, 2) if jornadas_emp > 0 else 0
    
    t = Table(table_data, colWidths=[120, 140, 140, 152])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f2937')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#ffffff'), colors.HexColor('#f9fafb')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    elements.append(t)
    elements.append(Spacer(1, 20))
    
    resumen_data = [
        [Paragraph("<b>Resumen del Periodo</b>", ParagraphStyle('HBox', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1f2937'))), ""],
        ["Jornadas Totales Completadas:", f"{jornadas_emp}"],
        ["Promedio Diario de Horas:", f"{promedio_empleado} hrs"],
        ["Horas Acumuladas Totales:", f"{round(total_horas_emp, 2)} hrs"]
    ]
    
    t_resumen = Table(resumen_data, colWidths=[200, 352])
    t_resumen.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fafafa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 1), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    elements.append(t_resumen)
    doc.build(elements, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    
    filename = f"reporte_{empleado.codigo}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


@app.route('/admin/reporte-general/pdf')
def descargar_reporte_general_pdf():
    if not session.get('is_admin'):
        return redirect(url_for('home'))
        
    empleados = Empleado.query.order_by(Empleado.nombre).all()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=40, bottomMargin=50)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#111827'), fontName='Helvetica-Bold', spaceAfter=4)
    subtitle_style = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontSize=9, leading=12, textColor=colors.HexColor('#4b5563'), fontName='Helvetica', spaceAfter=15)
    
    elements.append(Paragraph("<b>Reporte General Consolidado de Asistencia</b>", title_style))
    elements.append(Paragraph(f"Resumen Global &nbsp;|&nbsp; Generado el: {obtener_ahora_rd().strftime('%d/%m/%Y %I:%M %p')}", subtitle_style))
    elements.append(Spacer(1, 10))
    
    total_horas_empresa = 0
    total_jornadas_empresa = 0
    datos_empleados_cache = []
    chart_data_labels = []
    chart_data_values = []
    
    for empleado in empleados:
        asistencias = Asistencia.query.filter_by(empleado_id=empleado.id).order_by(Asistencia.timestamp).all()
        sesiones_por_dia = {}
        for reg in asistencias:
            fecha_str = reg.timestamp.strftime("%d/%m/%Y")
            if fecha_str not in sesiones_por_dia:
                sesiones_por_dia[fecha_str] = {"entrada": None, "salida": None}
            if reg.tipo == "ENTRADA" and not sesiones_por_dia[fecha_str]["entrada"]:
                sesiones_por_dia[fecha_str]["entrada"] = reg.timestamp
            elif reg.tipo == "SALIDA":
                sesiones_por_dia[fecha_str]["salida"] = reg.timestamp
                
        total_horas_emp = 0
        jornadas_emp = 0
        for fecha_str, tiempos in sesiones_por_dia.items():
            if tiempos["entrada"] and tiempos["salida"]:
                duracion = (tiempos["salida"] - tiempos["entrada"]).total_seconds() / 3600
                if 0 < duracion < 16:
                    total_horas_emp += duracion
                    jornadas_emp += 1
                    
        total_horas_empresa += total_horas_emp
        total_jornadas_empresa += jornadas_emp
        promedio_empleado = round(total_horas_emp / jornadas_emp, 2) if jornadas_emp > 0 else 0
        
        datos_empleados_cache.append({
            'empleado': empleado,
            'sesiones': sesiones_por_dia,
            'total_horas': total_horas_emp,
            'jornadas': jornadas_emp,
            'promedio': promedio_empleado
        })
        chart_data_labels.append(empleado.nombre.split()[0])
        chart_data_values.append(round(total_horas_emp, 1))

    elements.append(Paragraph("<b>Métricas Generales del Conjunto</b>", ParagraphStyle('HBoxGlobal', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor('#1f2937'), spaceAfter=8)))
    
    promedio_general_empresa = round(total_horas_empresa / total_jornadas_empresa, 2) if total_jornadas_empresa > 0 else 0
    global_summary_data = [
        ["Total de Empleados en el Sistema:", len(empleados)],
        ["Jornadas Totales Completadas:", total_jornadas_empresa],
        ["Horas Acumuladas Globales de la Empresa:", f"{round(total_horas_empresa, 2)} hrs"],
        ["Promedio General de Horas por Jornada:", f"{promedio_general_empresa} hrs"]
    ]
    
    t_global = Table(global_summary_data, colWidths=[230, 322])
    t_global.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3f4f6')),
        ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#fafafa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(t_global)
    elements.append(Spacer(1, 15))
    
    elements.append(Paragraph("<b>Estadísticas: Horas Totales Acumuladas por Empleado</b>", ParagraphStyle('HBoxChart', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor('#1f2937'), spaceAfter=8)))
    if empleados and any(chart_data_values):
        d = Drawing(552, 200)
        chart = VerticalBarChart()
        chart.x = 40
        chart.y = 20
        chart.height = 150
        chart.width = 490
        chart.data = [chart_data_values]
        chart.categoryAxis.categoryNames = chart_data_labels
        chart.categoryAxis.labels.fontSize = 8
        chart.categoryAxis.labels.angle = 20
        chart.categoryAxis.labels.dy = -10
        chart.valueAxis.valueMin = 0
        chart.bars[0].fillColor = colors.HexColor('#1f2937')
        chart.bars[0].strokeColor = colors.HexColor('#111827')
        d.add(chart)
        elements.append(d)
    else:
        elements.append(Paragraph("No hay suficientes registros de horas para mostrar el gráfico estadístico.", subtitle_style))
        
    elements.append(PageBreak())
    
    for index, item in enumerate(datos_empleados_cache):
        empleado = item['empleado']
        sesiones_por_dia = item['sesiones']
        total_horas_emp = item['total_horas']
        jornadas_emp = item['jornadas']
        promedio_empleado = item['promedio']
        
        elements.append(Paragraph(f"Reporte de Asistencia: <b>{empleado.nombre}</b>", title_style))
        elements.append(Paragraph(f"Código: <b>{empleado.codigo}</b> &nbsp;|&nbsp; Generado el: {obtener_ahora_rd().strftime('%d/%m/%Y %I:%M %p')}", subtitle_style))
        elements.append(Spacer(1, 5))
        
        table_data = [["Fecha", "Hora Entrada", "Hora Salida", "Total Horas"]]
        for fecha_str, tiempos in sorted(sesiones_por_dia.items(), reverse=True):
            entrada_str = tiempos["entrada"].strftime("%I:%M:%S %p") if tiempos["entrada"] else "Sin registro"
            salida_str = tiempos["salida"].strftime("%I:%M:%S %p") if tiempos["salida"] else "Pendiente"
            
            duracion_str = "-"
            if tiempos["entrada"] and tiempos["salida"]:
                duracion = (tiempos["salida"] - tiempos["entrada"]).total_seconds() / 3600
                if 0 < duracion < 16:
                    duracion_str = f"{round(duracion, 2)} hrs"
            
            table_data.append([fecha_str, entrada_str, salida_str, duracion_str])
            
        t = Table(table_data, colWidths=[120, 140, 140, 152])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f2937')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#ffffff'), colors.HexColor('#f9fafb')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 15))
        
        resumen_data = [
            [Paragraph("<b>Resumen del Periodo</b>", ParagraphStyle('HBox', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1f2937'))), ""],
            ["Jornadas Totales Completadas:", f"{jornadas_emp}"],
            ["Promedio Diario de Horas:", f"{promedio_empleado} hrs"],
            ["Horas Acumuladas Totales:", f"{round(total_horas_emp, 2)} hrs"]
        ]
        t_resumen = Table(resumen_data, colWidths=[200, 352])
        t_resumen.setStyle(TableStyle([
            ('SPAN', (0, 0), (1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fafafa')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 1), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(t_resumen)
        
        if index < len(datos_empleados_cache) - 1:
            elements.append(PageBreak())
            
    doc.build(elements, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    filename = f"reporte_general_por_empleado_{obtener_ahora_rd().strftime('%Y%m%d')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


@app.route('/admin/reporte-general/excel')
def descargar_reporte_general_excel():
    if not session.get('is_admin'):
        return redirect(url_for('home'))
        
    empleados = Empleado.query.order_by(Empleado.nombre).all()
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        todos_registros = []
        resumen_empleados = []
        
        for empleado in empleados:
            asistencias = Asistencia.query.filter_by(empleado_id=empleado.id).order_by(Asistencia.timestamp).all()
            sesiones_por_dia = {}
            for reg in asistencias:
                fecha_str = reg.timestamp.strftime("%d/%m/%Y")
                if fecha_str not in sesiones_por_dia:
                    sesiones_por_dia[fecha_str] = {"entrada": None, "salida": None}
                if reg.tipo == "ENTRADA" and not sesiones_por_dia[fecha_str]["entrada"]:
                    sesiones_por_dia[fecha_str]["entrada"] = reg.timestamp
                elif reg.tipo == "SALIDA":
                    sesiones_por_dia[fecha_str]["salida"] = reg.timestamp
            
            total_horas_emp = 0
            jornadas_emp = 0
            
            for fecha_str, tiempos in sorted(sesiones_por_dia.items(), reverse=True):
                entrada_str = tiempos["entrada"].strftime("%I:%M:%S %p") if tiempos["entrada"] else "Sin registro"
                salida_str = tiempos["salida"].strftime("%I:%M:%S %p") if tiempos["salida"] else "Pendiente"
                
                duracion = 0
                if tiempos["entrada"] and tiempos["salida"]:
                    duracion_calc = (tiempos["salida"] - tiempos["entrada"]).total_seconds() / 3600
                    if 0 < duracion_calc < 16:
                        total_horas_emp += duracion_calc
                        jornadas_emp += 1
                        duracion = round(duracion_calc, 2)
                
                todos_registros.append({
                    "Código": empleado.codigo,
                    "Empleado": empleado.nombre,
                    "Fecha": fecha_str,
                    "Hora Entrada": entrada_str,
                    "Hora Salida": salida_str,
                    "Total Horas": duracion
                })
            
            promedio_empleado = round(total_horas_emp / jornadas_emp, 2) if jornadas_emp > 0 else 0
            resumen_empleados.append({
                "Código": empleado.codigo,
                "Empleado": empleado.nombre,
                "Jornadas Completadas": jornadas_emp,
                "Promedio Diario (hrs)": promedio_empleado,
                "Horas Totales Acumuladas": round(total_horas_emp, 2)
            })
            
        df_detallado = pd.DataFrame(todos_registros)
        df_resumen = pd.DataFrame(resumen_empleados)
        df_detallado.to_excel(writer, sheet_name='Detalle por Ponches', index=False)
        df_resumen.to_excel(writer, sheet_name='Resumen General', index=False)
        
    output.seek(0)
    filename = f"reporte_asistencia_{obtener_ahora_rd().strftime('%Y%m%d')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/api/cambiar-password', methods=['POST'])
def cambiar_password():
    if not session.get('is_admin'):
        return jsonify({"error": "No autorizado"}), 401
    data = request.get_json()
    actual = data.get('actual')
    nueva = data.get('nueva')
    admin_config = Configuracion.query.filter_by(clave='admin_password').first()
    if not admin_config or admin_config.valor != actual:
        return jsonify({"error": "La contraseña actual es incorrecta."}), 400
    if not nueva or len(nueva) < 3:
        return jsonify({"error": "La nueva contraseña es muy corta."}), 400
    admin_config.valor = nueva
    db.session.commit()
    return jsonify({"mensaje": "¡Contraseña actualizada con éxito!"})


# --- RUTAS DE LA API ---

@app.route('/api/ponchar', methods=['POST'])
def registrar_ponche():
    data = request.get_json()
    codigo = data.get('codigo')
    if not codigo:
        return jsonify({"error": "El código es obligatorio."}), 400
    
    empleado = Empleado.query.filter_by(codigo=codigo).first()
    if not empleado:
        return jsonify({"error": "Empleado no encontrado."}), 404
    
    ahora_rd = obtener_ahora_rd()
    hoy_inicio = ahora_rd.replace(hour=0, minute=0, second=0, microsecond=0)
    
    ultimo_registro = Asistencia.query.filter(
        Asistencia.empleado_id == empleado.id,
        Asistencia.timestamp >= hoy_inicio
    ).order_by(Asistencia.timestamp.desc()).first()
    
    if not ultimo_registro or ultimo_registro.tipo == "SALIDA":
        nuevo_tipo = "ENTRADA"
    else:
        nuevo_tipo = "SALIDA"
        
    nuevo_ponche = Asistencia(
        empleado_id=empleado.id,
        tipo=nuevo_tipo,
        timestamp=ahora_rd
    )
    db.session.add(nuevo_ponche)
    db.session.commit()
    
    return jsonify({
        "mensaje": "¡Registro exitoso!",
        "empleado": empleado.nombre,
        "tipo": nuevo_tipo,
        # Formato de hora en 12 horas (AM/PM) estándar dominicano (ej: 03:45:12 p. m.)
        "hora": ahora_rd.strftime("%I:%M:%S %p"),
        "foto": empleado.foto
    })

@app.route('/api/empleados/siguiente-codigo', methods=['GET'])
def siguiente_codigo():
    total_actual = Empleado.query.count()
    codigo = f"EMP{str(total_actual + 1).zfill(3)}"
    while Empleado.query.filter_by(codigo=codigo).first():
        total_actual += 1
        codigo = f"EMP{str(total_actual + 1).zfill(3)}"
    return jsonify({"codigo": codigo})

@app.route('/api/empleados', methods=['POST'])
def crear_empleado():
    if not session.get('is_admin'):
        return jsonify({"error": "No autorizado"}), 401
    nombre = request.form.get('nombre')
    if not nombre:
        return jsonify({"error": "El nombre es obligatorio."}), 400
        
    total_actual = Empleado.query.count()
    codigo = f"EMP{str(total_actual + 1).zfill(3)}"
    while Empleado.query.filter_by(codigo=codigo).first():
        total_actual += 1
        codigo = f"EMP{str(total_actual + 1).zfill(3)}"
        
    nombre_foto = 'default.png'
    if 'foto' in request.files:
        file = request.files['foto']
        if file.filename != '':
            filename = secure_filename(f"emp_{codigo}_{file.filename}")
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            nombre_foto = filename
        
    emp = Empleado(codigo=codigo, nombre=nombre, foto=nombre_foto)
    db.session.add(emp)
    db.session.commit()
    
    return jsonify({
        "mensaje": f"¡Empleado {nombre} registrado con éxito!",
        "id": emp.id,
        "codigo": emp.codigo,
        "nombre": emp.nombre,
        "foto": emp.foto
    }), 201


@app.route('/admin/empleado/<int:empleado_id>/foto', methods=['POST'])
def actualizar_foto(empleado_id):
    if not session.get('is_admin'):
        return jsonify({"error": "No autorizado"}), 401
    empleado = Empleado.query.get_or_404(empleado_id)
    if 'foto' in request.files:
        file = request.files['foto']
        if file.filename != '':
            filename = secure_filename(f"emp_{empleado.id}_{file.filename}")
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            empleado.foto = filename
            db.session.commit()
            return jsonify({"mensaje": "Foto actualizada con éxito."})
    return jsonify({"error": "No se subió ninguna imagen."}), 400


if __name__ == '__main__':
    app.run(debug=True, port=5000)