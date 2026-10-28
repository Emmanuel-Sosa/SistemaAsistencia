from app import app, db, Empleado  # Asumiendo que tu archivo principal se llama app.py

with app.app_context():
    # Crear un nuevo empleado
    nuevo_empleado = Empleado(codigo="EMP002", nombre="Juan")
    
    # Guardarlo en la base de datos
    db.session.add(nuevo_empleado)
    db.session.commit()
    print("¡Empleado agregado con éxito!")
    
    

with app.app_context():
    empleados = Empleado.query.all()
    print(f"Total de empleados encontrados: {len(empleados)}")
    for emp in empleados:
        print(f"ID: {emp.id} | Código: {emp.codigo} | Nombre: {emp.nombre}")