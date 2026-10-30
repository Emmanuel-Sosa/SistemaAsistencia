// ==========================================
// MODO OSCURO (Común en varias páginas)
// ==========================================
const btnToggleTheme = document.getElementById('btnToggleTheme');
const body = document.body;

if (localStorage.getItem('darkMode') === 'true' || localStorage.getItem('theme') === 'dark') {
    body.classList.add('dark-mode');
    if (btnToggleTheme) btnToggleTheme.textContent = '☀️ Cambiar a Modo Claro';
}

if (btnToggleTheme) {
    btnToggleTheme.addEventListener('click', (e) => {
        e.preventDefault();
        body.classList.toggle('dark-mode');
        const isDark = body.classList.contains('dark-mode');
        localStorage.setItem('darkMode', isDark);
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
        btnToggleTheme.textContent = isDark ? '☀️ Cambiar a Modo Claro' : '🌙 Cambiar a Modo Oscuro';
    });
}


// ==========================================
// ADMIN: Cambio de contraseña
// ==========================================
const formPassword = document.getElementById('formPassword');
if (formPassword) {
    formPassword.addEventListener('submit', async (e) => {
        e.preventDefault();
        const actual = document.getElementById('pwdActual').value;
        const nueva = document.getElementById('pwdNueva').value;
        const msgDiv = document.getElementById('msgPassword');

        try {
            const response = await fetch('/api/cambiar-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ actual, nueva })
            });
            const data = await response.json();
            
            if (response.ok) {
                msgDiv.innerHTML = `<div class="alert alert-success py-2 mb-0">${data.mensaje}</div>`;
                setTimeout(() => { location.reload(); }, 1500);
            } else {
                msgDiv.innerHTML = `<div class="alert alert-danger py-2 mb-0">${data.error}</div>`;
            }
        } catch (err) {
            msgDiv.innerHTML = `<div class="alert alert-danger py-2 mb-0">Error de conexión.</div>`;
        }
    });
}


// ==========================================
// EMPLEADO DETALLE (Carnet y Gráficos)
// ==========================================
const modalCarnet = document.getElementById('modalCarnet');
if (modalCarnet) {
    modalCarnet.addEventListener('shown.bs.modal', function () {
        const qrContainer = document.getElementById('qrcode');
        if (!qrContainer) return;
        qrContainer.innerHTML = ""; 
        
        // Nota: Si esto está en un archivo JS externo, cuidado con las variables de Jinja embebidas si no se renderizan bien.
        const urlPonche = window.location.origin + "/?codigo=" + (document.getElementById('modalCodigo')?.innerText || '');

        new QRCode(qrContainer, {
            text: urlPonche,
            width: 128,
            height: 128,
            colorDark : "#000000",
            colorLight : "#ffffff",
            correctLevel : QRCode.CorrectLevel.H
        });
    });
}

const formFoto = document.getElementById('formFoto');
if (formFoto) {
    formFoto.addEventListener('submit', async function(e) {
        e.preventDefault();
        const input = document.getElementById('inputFoto');
        if(!input || input.files.length === 0) return;

        const formData = new FormData();
        formData.append('foto', input.files[0]);

        // Extraer id de la URL actual o elemento si es necesario
        try {
            const response = await fetch(window.location.pathname + '/foto', {
                method: 'POST',
                body: formData
            });
            if(response.ok) {
                location.reload();
            } else {
                alert('Error al subir la foto');
            }
        } catch (err) {
            alert('Error de conexión');
        }
    });
}

const graficoHoras = document.getElementById('graficoHoras');
if (graficoHoras && typeof diasLabels !== 'undefined' && typeof horasData !== 'undefined') {
    const ctx = graficoHoras.getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: diasLabels,
            datasets: [{
                label: 'Horas Trabajadas',
                data: horasData,
                backgroundColor: 'rgba(13, 110, 253, 0.7)',
                borderColor: 'rgba(13, 110, 253, 1)',
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    title: { display: true, text: 'Horas' }
                }
            }
        }
    });
}


// ==========================================
// INDEX (Sistema de Ponche principal)
// ==========================================
async function ejecutarPonche(codigo) {
    const resDiv = document.getElementById('resultadoPonche');
    if (!resDiv || !codigo) return;

    try {
        const response = await fetch('/api/ponchar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ codigo })
        });
        const data = await response.json();

        if (response.ok) {
            let elementoFoto = '';
            if (data.foto && data.foto !== 'default.png') {
                elementoFoto = `<img src="/static/uploads/${data.foto}" class="rounded-circle border shadow-sm flex-shrink-0" width="60" height="60" style="object-fit: cover;" alt="Foto">`;
            } else {
                let inicial = data.empleado ? data.empleado[0].toUpperCase() : '?';
                elementoFoto = `<div class="rounded-circle bg-success text-white d-flex align-items-center justify-content-center shadow-sm flex-shrink-0" style="width: 60px; height: 60px; font-size: 1.5rem; font-weight: bold;">${inicial}</div>`;
            }

            resDiv.innerHTML = `
                <div class="alert alert-success p-3 mb-0 shadow-sm text-start d-flex align-items-center gap-3 border-0">
                    ${elementoFoto}
                    <div>
                        <h5 class="fw-bold mb-1 text-dark">${data.empleado}</h5>
                        <div><span class="badge bg-success">${data.tipo}</span> <span class="small text-muted">a las ${data.hora}</span></div>
                    </div>
                </div>
            `;
        } else {
            resDiv.innerHTML = `<div class="alert alert-danger py-2 mb-0 shadow-sm">${data.error}</div>`;
        }
        const inputCodigo = document.getElementById('codigo');
        if(inputCodigo) {
            inputCodigo.value = '';
            inputCodigo.focus();
        }
    } catch (err) {
        resDiv.innerHTML = `<div class="alert alert-danger py-2 mb-0 shadow-sm">Error de conexión.</div>`;
    }
}

const formPonche = document.getElementById('formPonche');
if (formPonche) {
    formPonche.addEventListener('submit', function(e) {
        e.preventDefault();
        const codigoInput = document.getElementById('codigo');
        if (codigoInput) {
            const codigo = codigoInput.value.trim();
            ejecutarPonche(codigo);
        }
    });

    window.addEventListener('DOMContentLoaded', () => {
        const urlParams = new URLSearchParams(window.location.search);
        const codigoUrl = urlParams.get('codigo');
        if (codigoUrl) {
            ejecutarPonche(codigoUrl);
            window.history.replaceState({}, document.title, window.location.pathname);
        } else {
            const inputCodigo = document.getElementById('codigo');
            if(inputCodigo) inputCodigo.focus();
        }
    });
}


// ==========================================
// LOGIN ADMIN
// ==========================================
const formLoginAdmin = document.getElementById('formLoginAdmin');
if (formLoginAdmin) {
    formLoginAdmin.addEventListener('submit', async function(e) {
        e.preventDefault();
        const password = document.getElementById('adminPass').value;
        const alerta = document.getElementById('alertaLogin');

        try {
            const response = await fetch('/admin/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password })
            });

            if (response.ok) {
                alerta.innerHTML = `<span class="text-success fw-bold">¡Acceso concedido! Redirigiendo...</span>`;
                setTimeout(() => { window.location.href = '/admin'; }, 800);
            } else {
                alerta.innerHTML = `<span class="text-danger fw-bold">Contraseña incorrecta.</span>`;
            }
        } catch (err) {
            alerta.innerHTML = `<span class="text-danger fw-bold">Error de conexión.</span>`;
        }
    });
}


// ==========================================
// NUEVO EMPLEADO
// ==========================================
const formNuevoEmpleado = document.getElementById('formNuevoEmpleado');
if (formNuevoEmpleado) {
    async function cargarSiguienteCodigo() {
        try {
            const response = await fetch('/api/empleados/siguiente-codigo');
            const data = await response.json();
            const lbl = document.getElementById('lblCodigo');
            if (response.ok && lbl) {
                lbl.innerText = data.codigo;
            } else if (lbl) {
                lbl.innerText = 'EMP???';
            }
        } catch (error) {
            const lbl = document.getElementById('lblCodigo');
            if (lbl) lbl.innerText = 'Error';
        }
    }

    cargarSiguienteCodigo();

    formNuevoEmpleado.addEventListener('submit', async function(e) {
        e.preventDefault();
        const nombre = document.getElementById('nombre').value.trim();
        const fotoInput = document.getElementById('foto');
        const alertaDiv = document.getElementById('mensajeAlerta');

        const formData = new FormData();
        formData.append('nombre', nombre);
        if (fotoInput && fotoInput.files.length > 0) {
            formData.append('foto', fotoInput.files[0]);
        }

        try {
            const response = await fetch('/api/empleados', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                document.getElementById('modalNombre').innerText = data.nombre;
                document.getElementById('modalCodigo').innerText = data.codigo;
                
                const fotoContainer = document.getElementById('modalFotoContenedor');
                if (data.foto && data.foto !== 'default.png') {
                    fotoContainer.innerHTML = `<img src="/static/uploads/${data.foto}" class="rounded-circle border" width="90" height="90" style="object-fit: cover;" alt="Foto">`;
                } else {
                    fotoContainer.innerHTML = `<div class="rounded-circle bg-secondary text-white d-flex align-items-center justify-content-center mx-auto border" style="width: 90px; height: 90px; font-size: 2rem;">${data.nombre[0].toUpperCase()}</div>`;
                }

                document.getElementById('qrcode').innerHTML = "";
                const urlPoncheNuevo = window.location.origin + "/?codigo=" + data.codigo;

                new QRCode(document.getElementById('qrcode'), {
                    text: urlPoncheNuevo,
                    width: 128,
                    height: 128,
                    colorDark : "#000000",
                    colorLight : "#ffffff",
                    correctLevel : QRCode.CorrectLevel.H
                });

                const modalCarnetInstance = new bootstrap.Modal(document.getElementById('modalCarnet'));
                modalCarnetInstance.show();

            } else {
                alertaDiv.innerHTML = `<span class="text-danger fw-bold">${data.error}</span>`;
            }
        } catch (error) {
            alertaDiv.innerHTML = `<span class="text-danger fw-bold">Error de conexión con el servidor.</span>`;
        }
    });
}
