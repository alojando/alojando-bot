#!/usr/bin/env python3
"""
Alojando BOT - Iniciar servidor web.
Ejecuta: python start_web.py
Abre: http://localhost:5000
"""
import subprocess
import sys
import os

def main():
    # Verificar/instalar dependencias
    print("Verificando dependencias...")
    req_file = os.path.join(os.path.dirname(__file__), "web", "requirements.txt")

    try:
        import flask
        import flask_cors
    except ImportError:
        print("Instalando dependencias web...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])

    # Iniciar servidor
    app_path = os.path.join(os.path.dirname(__file__), "web", "app.py")
    os.environ.setdefault("FLASK_DEBUG", "false")
    subprocess.call([sys.executable, app_path])

if __name__ == "__main__":
    main()
