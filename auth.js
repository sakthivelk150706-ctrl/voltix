/*
  DROP-IN REPLACEMENT for the old auth logic in index.html.

  What to REMOVE from your current index.html:
    - The line that does: users = await fetch(BASE_URL + '/api/users')...
      (this is the line that leaked every plaintext password to every visitor)
    - Any client-side check like `if (verificationCode === "VOLTIX")`
    - Any place that stores `pass` inside `currentUser` or localStorage

  What to ADD: the functions below. They talk to the new server.py, which
  never sends passwords anywhere and issues a session token instead.
*/

const BASE_URL = "https://voltix-4qsh.onrender.com"; // update if you redeploy elsewhere

// Store only the token + role + name — never the password.
function saveSession(token, role, name) {
  localStorage.setItem("voltixToken", token);
  localStorage.setItem("voltixRole", role);
  localStorage.setItem("voltixName", name);
}

function clearSession() {
  localStorage.removeItem("voltixToken");
  localStorage.removeItem("voltixRole");
  localStorage.removeItem("voltixName");
}

function getToken() {
  return localStorage.getItem("voltixToken");
}

// Attach this to every authenticated fetch call instead of sending user info
// in the body. Example: apiFetch('/api/products', {method:'POST', body:...})
async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = Object.assign({}, options.headers, {
    "Content-Type": "application/json",
  });
  if (token) headers["Authorization"] = "Bearer " + token;

  const res = await fetch(BASE_URL + path, Object.assign({}, options, { headers }));
  if (res.status === 401) {
    // Session expired or invalid — force re-login.
    clearSession();
    alert("Your session has expired. Please log in again.");
    location.reload();
    return null;
  }
  return res;
}

async function signup(email, name, password) {
  const res = await fetch(BASE_URL + "/api/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, name, password }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Signup failed");
  saveSession(data.token, data.role, data.name);
  return data;
}

async function login(email, password) {
  const res = await fetch(BASE_URL + "/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Login failed");
  saveSession(data.token, data.role, data.name);
  return data;
}

async function logout() {
  await apiFetch("/api/logout", { method: "POST" });
  clearSession();
  location.reload();
}

// Example: how the old "signup with role + code" form should now look —
// just email/name/password. No role field, no verification code field.
// Every new account is a buyer. Sellers/admins get promoted server-side
// by an existing admin (see create_first_admin.py + /api/admin/promote).
