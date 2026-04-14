#!/usr/bin/env python3
"""
Alojando BOT - Script de ejecución directa.
Uso: python run.py [argumentos]

Ejemplos:
    python run.py --demo                          # Ejecutar con datos demo
    python run.py --url https://airbnb.com/...    # Analizar una URL
    python run.py --manual                        # Ingreso interactivo
    python run.py --data '{"city":"Buenos Aires","price":80}'
    python run.py --help                          # Ver toda la ayuda
"""
import sys
import os

# Agregar el directorio padre al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alojando_bot.main import main

if __name__ == "__main__":
    main()
