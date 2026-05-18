const DEFAULT_URL = "https://digivault.digilatics.co";

// ------------------------------------------------------------------
// Server URL form
// ------------------------------------------------------------------

const optionsForm = document.getElementById("options-form");
const serverInput = document.getElementById("server-url");
const serverStatus = document.getElementById("server-status");

chrome.storage.sync.get("serverUrl", ({ serverUrl }) => {
  serverInput.value = serverUrl || DEFAULT_URL;
});

optionsForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const value = serverInput.value.trim() || DEFAULT_URL;
  chrome.storage.sync.set({ serverUrl: value }, () => {
    serverStatus.textContent = "Saved.";
    setTimeout(() => { serverStatus.textContent = ""; }, 1500);
  });
});

// ------------------------------------------------------------------
// Auth state display
// ------------------------------------------------------------------

function showAuthState() {
  chrome.storage.local.get(["access", "email"], ({ access, email }) => {
    const loggedIn = !!access;
    document.getElementById("logged-in-section").style.display = loggedIn ? "" : "none";
    document.getElementById("login-section").style.display = loggedIn ? "none" : "";
    if (loggedIn && email) {
      document.getElementById("logged-in-email").textContent = email;
    }
  });
}

showAuthState();

// ------------------------------------------------------------------
// Login form
// ------------------------------------------------------------------

const loginForm = document.getElementById("login-form");
const loginStatus = document.getElementById("login-status");

function setLoginStatus(msg, isError) {
  loginStatus.textContent = msg;
  loginStatus.className = `status-msg ${isError ? "err" : "ok"}`;
}

loginForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  if (!email || !password) {
    setLoginStatus("Email and password are required.", true);
    return;
  }

  setLoginStatus("Logging in…", false);

  chrome.runtime.sendMessage({ type: "LOGIN", email, password }, (result) => {
    if (chrome.runtime.lastError || !result) {
      setLoginStatus("Could not reach background service. Reload the extension.", true);
      return;
    }
    if (result.error) {
      setLoginStatus(result.error === "network" ? "Could not reach server. Check the Server URL below." : result.error, true);
      return;
    }
    document.getElementById("login-password").value = "";
    setLoginStatus("", false);
    showAuthState();
  });
});

// ------------------------------------------------------------------
// Logout
// ------------------------------------------------------------------

document.getElementById("logout-btn").addEventListener("click", async () => {
  await chrome.storage.local.remove(["access", "refresh", "email"]);
  showAuthState();
});
