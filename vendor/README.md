# Dependencia vendorizada

El paquete offline final debe incluir `python-3.12.10-amd64.exe` únicamente para
regenerar un entorno de build aislado cuando no exista Python 3.12. El runtime
PyInstaller instalado en la máquina destino no utiliza este instalador.

Archivo vendorizado:

```text
python-3.12.10-amd64.exe
SHA-256 67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB
```

Fue descargado desde `https://www.python.org/ftp/python/3.12.10/` el 27 de julio
de 2026. Antes de reemplazarlo, verifique nuevamente el hash y registre el valor
en las notas de release.
