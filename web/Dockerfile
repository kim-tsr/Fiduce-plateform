# syntax=docker/dockerfile:1
# Frontend statique servi par nginx en mode non privilégié (UID 101, port 8080).
# Contexte de build attendu : ce dossier web/.
#   docker build -t fiduce/web web/
FROM nginxinc/nginx-unprivileged:1.31.7-alpine-slim@sha256:a8cb0f33d51fa107c96fd2bd3a71aaf564ec131e9d2bdf8700944f0ed8b170d7

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html app.html styles.css api.js auth.js dashboard.js /usr/share/nginx/html/

EXPOSE 8080
