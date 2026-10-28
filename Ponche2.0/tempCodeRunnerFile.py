from datetime import datetime
from flask import Flask, request, jsonify, render_template  # 1. Aquí va la importación nueva
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///asistencia.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- MODELOS DE BASE DE DATOS ---
class Empleado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)

class Asistencia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    empleado_id = db.Column(db.Integer, db.ForeignKey('empleado.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    tipo = db.Column(db.String(20), nullable=False)  # "ENTRADA" o "SALIDA"

# Crear tablas automáticamente
with app.app_context():
    db.create_all()

# --- 2. NUEVA RUTA PARA MOSTRAR LA PÁGINA WEB ---
@app.route('/')
def home():
    return render_template('index.html')  # Busca index.html dentro de la carpeta templates


# --- RUTAS DE LA API (Estas ya las tenías) ---

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
        "hora": datetime.now().strftime("%H:%M:%S")
    })

@app.route('/api/empleados', methods=['POST'])
def crear_empleado():
    data = request.get_json()
    codigo = data.get('codigo')
    nombre = data.get('nombre')
    
    if not codigo or not nombre:
        return jsonify({"error": "Faltan datos."}), 400
        
    if Empleado.query.filter_by(codigo=codigo).first():
        return jsonify({"error": "Este código ya existe."}), 400
        
    emp = Empleado(codigo=codigo, nombre=nombre)
    db.session.add(emp)
    db.session.commit()
    
    return jsonify({"mensaje": f"Empleado {nombre} registrado con éxito."}), 201


if __name__ == '__main__':
    app.run(debug=True, port=5000)
    
