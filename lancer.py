#!/usr/bin/env python3
"""
Lance l'app Voyage Norvège sur un serveur local.
Nécessaire pour les tracés ORS et la météo (APIs bloquées en file://).
"""
import subprocess, sys, os, time, webbrowser, socket

PORT = 8080
os.chdir(os.path.dirname(os.path.abspath(__file__)))

def port_libre(p):
    with socket.socket() as s:
        return s.connect_ex(('localhost', p)) != 0

if not port_libre(PORT):
    PORT = 8081

print(f"\n✈️  Voyage Norvège – Été 2026")
print(f"{'─'*40}")
print(f"Ouverture dans le navigateur…")
print(f"URL locale : http://localhost:{PORT}")
print(f"Arrêt      : Ctrl+C\n")

srv = subprocess.Popen([sys.executable,'-m','http.server',str(PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.2)
webbrowser.open(f'http://localhost:{PORT}/voyage.html')

try:
    srv.wait()
except KeyboardInterrupt:
    srv.terminate()
    print("\nServeur arrêté.")
