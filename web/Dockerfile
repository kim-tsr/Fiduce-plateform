# syntax=docker/dockerfile:1
# Frontend statique servi par nginx en mode non privilégié (UID 101, port 8080).
# Contexte de build attendu : ce dossier web/.
#   docker build -t fiduce/web web/
FROM nginxinc/nginx-unprivileged:1.31.6-alpine-slim@sha256:1517d8c358e2e093957ebee087afa9eb19a32f5d7ecb711b7429e369cb998224

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html app.html styles.css api.js auth.js dashboard.js /usr/share/nginx/html/

EXPOSE 8080
