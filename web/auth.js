"use strict";
// Page de connexion. En cas de succès -> VRAIE redirection vers /app.html.

// Si une session valide existe déjà, on file directement au dashboard.
(async function redirectIfLoggedIn() {
  if (!token()) return;
  try {
    await api("/auth/userinfo");
    location.replace("/app.html");
  } catch (_) {
    sessionStorage.clear(); // token périmé : on reste sur le login, proprement
  }
})();

const form = $("#login-form");
const btn = $("#login-submit");
const err = $("#login-error");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(form);
  err.hidden = true;
  btn.disabled = true;
  btn.dataset.loading = "true";
  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: {
        tenant: f.get("tenant"),
        username: f.get("username"),
        password: f.get("password"),
      },
    });
    sessionStorage.setItem("fiduce_token", data.access_token);
    sessionStorage.setItem("fiduce_who", `${f.get("username")}@${f.get("tenant")}`);
    location.assign("/app.html"); // redirection vers le dashboard
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
    btn.disabled = false;
    btn.dataset.loading = "false";
  }
});
