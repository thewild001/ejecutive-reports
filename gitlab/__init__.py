"""Informes GitLab de la suite.

OJO: este paquete se llama `gitlab` igual que la librería python-gitlab (usada por
mcp/gitlab-mcp). Al ser un paquete regular con __init__.py, gana cuando la raíz
del proyecto va primero en sys.path (lo hacen los scripts de la suite); sin este
archivo sería un paquete "namespace" y python-gitlab, si está en el mismo venv, lo
taparía. El servidor MCP corre como script (mcp/gitlab-mcp), donde `import gitlab`
resuelve a python-gitlab.
"""
