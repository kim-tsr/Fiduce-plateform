# syntax=docker/dockerfile:1
# Frontend statique servi par nginx en mode non privilégié (UID 101, port 8080).
# Contexte de build attendu : ce dossier web/.
#   docker build -t fiduce/web web/
FROM nginxinc/nginx-unprivileged:1.31.6-alpine-slim@sha256:ac4d9c7e457c6510b95ac72dd84b27f7cc68ecb9a83fbd44f05a6460cf08aba4

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html app.html styles.css api.js auth.js dashboard.js /usr/share/nginx/html/

EXPOSE 8080
