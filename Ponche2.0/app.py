import os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'clave_secreta_super_segura' # Necesario para las sesiones de administrador

# Configuración de ruta absoluta para la base de datos
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'asistencia.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configuración de la carpeta para las fotos de los empleados
UPLOAD_FOLDER = 'static/uploads'
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
    timestamp = db.Column(db.DateTime, default=datetime.now)
    tipo = db.Column(db.String(20), nullable=False)  # "ENTRADA" o "SALIDA"

class Configuracion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(50), unique=True, nullable=False)
    valor = db.Column(db.String(200), nullable=False)

# Crear tablas y configuración inicial automáticamente
with app.app_context():
    db.create_all()
    # Si no existe contraseña de admin, creamos una por defecto "admin"
    admin_config = Configuracion.query.filter_by(clave='admin_password').first()
    if not admin_config:
        db.session.add(Configuracion(clave='admin_password', valor='admin'))
        db.session.commit()

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
        hoy_inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Empleados activos hoy
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
                    "hora_llegada": ultimo.timestamp.strftime("%H:%M:%S")
                })

        # Historial general (últimos 50)
        historial_raw = Asistencia.query.join(Empleado).add_columns(
            Empleado.nombre, Empleado.codigo, Asistencia.timestamp, Asistencia.tipo
        ).order_by(Asistencia.timestamp.desc()).limit(50).all()
        
        historial = [{
            "nombre": h.nombre,
            "codigo": h.codigo,
            "fecha_hora": h.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "tipo": h.tipo
        } for h in historial_raw]

        # Promedio general de la empresa
        asistencias_todas = Asistencia.query.order_by(Asistencia.timestamp).all()
        sesiones_por_dia = {}
        for reg in asistencias_todas:
            fecha_str = reg.timestamp.strftime("%Y-%m-%d")
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
    hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    fin_periodo = hoy - timedelta(days=offset * 7)
    inicio_periodo = fin_periodo - timedelta(days=6)
    
    asistencias = Asistencia.query.filter_by(empleado_id=empleado.id).order_by(Asistencia.timestamp).all()
    
    sesiones_por_dia = {}
    for reg in asistencias:
        fecha_str = reg.timestamp.strftime("%Y-%m-%d")
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
        f_str = current_d.strftime("%Y-%m-%d")
        dias_grafico.append(current_d.strftime("%d/%m (%a)"))
        horas_grafico.append(horas_por_dia_map.get(f_str, 0))
        current_d += timedelta(days=1)

    return render_template('empleado_detalle.html',
                           empleado=empleado,
                           promedio_empleado=promedio_empleado,
                           dias_grafico=dias_grafico,
                           horas_grafico=horas_grafico,
                           offset=offset)


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
    
    hoy_inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
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
        timestamp=datetime.now()
    )
    db.session.add(nuevo_ponche)
    db.session.commit()
    
    return jsonify({
        "mensaje": "¡Registro exitoso!",
        "empleado": empleado.nombre,
        "tipo": nuevo_tipo,
        "hora": datetime.now().strftime("%H:%M:%S"),
        "foto": empleado.foto  # <--- Envía la foto para mostrarla en el ponche
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