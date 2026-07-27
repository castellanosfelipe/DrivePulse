# Dependencia vendorizada

El paquete offline final debe incluir `python-3.12.10-amd64.exe` únicamente para
regenerar un entorno de build aislado cuando no exista Python 3.12. El runtime
PyInstaller instalado en la máquina destino no utiliza este instalador.

Antes de una release, verifique el SHA-256 contra el publicado por Python.org y
registre el valor en las notas de la release.

