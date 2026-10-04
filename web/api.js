"use strict";
// Client partagé de la plateforme Fiduce (login + dashboard).
// Toutes les requêtes passent par la gateway via le préfixe /api (proxifié par
// nginx en local, par l'ingress en k8s). Aucune dépendance externe.

const API = "/api";
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const token = () => sessionStorage.getItem("fiduce_token");

async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  const t = token();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  const res = await fetch(API + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  // 401 sur une requête authentifiée = session expirée -> on déconnecte (et on
  // redirige vers le login). 401 sans token (login échoué) : on laisse remonter
  // le détail renvoyé par le serveur (ex. « Identifiants invalides »).
  if (res.status === 401 && t) {
    logout();
    throw new Error("Session expirée");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

const fmtMoney = (cents, cur = "EUR") =>
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: cur }).format(cents / 100);

// Déconnexion = on vide la session et on revient à l'écran de login (vraie
// navigation, pas de bascule de section dans la même page).
function logout() {
  sessionStorage.clear();
  location.replace("/");
}
