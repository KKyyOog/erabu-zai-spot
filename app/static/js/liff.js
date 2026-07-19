function clearLegacyLiffReturnUrl() {
  try {
    window.localStorage.removeItem("erabu_zai_spot_liff_return_url");
  } catch (error) {
    console.warn("Failed to clear legacy LIFF return URL:", error);
  }
}

const LIFF_LOGIN_ATTEMPT_KEY = "erabu_zai_spot_liff_login_attempted_at";
const LIFF_LOGIN_RETRY_DELAY_MS = 60 * 1000;

function recentlyAttemptedLiffLogin() {
  try {
    const attemptedAt = Number(window.sessionStorage.getItem(LIFF_LOGIN_ATTEMPT_KEY) || 0);
    return attemptedAt > 0 && Date.now() - attemptedAt < LIFF_LOGIN_RETRY_DELAY_MS;
  } catch (error) {
    console.warn("Failed to read LIFF login attempt:", error);
    return false;
  }
}

function rememberLiffLoginAttempt() {
  try {
    window.sessionStorage.setItem(LIFF_LOGIN_ATTEMPT_KEY, String(Date.now()));
  } catch (error) {
    console.warn("Failed to store LIFF login attempt:", error);
  }
}

function clearLiffLoginAttempt() {
  try {
    window.sessionStorage.removeItem(LIFF_LOGIN_ATTEMPT_KEY);
  } catch (error) {
    console.warn("Failed to clear LIFF login attempt:", error);
  }
}

function liffLoginRedirectUrl() {
  return `${window.location.origin}${window.location.pathname}`;
}

function hasFreshIdToken(idToken) {
  if (!idToken || !liff.getDecodedIDToken) {
    return false;
  }

  const decodedToken = liff.getDecodedIDToken();
  const expiresAt = Number(decodedToken?.exp || 0) * 1000;
  return expiresAt > Date.now() + 30 * 1000;
}

function restartLineAuthentication(reason) {
  logToServer(`Restarting LINE authentication: ${reason}`, getLiffDebugContext());
  window.LINE_ID_TOKEN = "";
  window.LINE_SESSION_AUTHENTICATED = false;
  setAllLineUserInputs("");

  if (liff.isInClient && liff.isInClient()) {
    setUserRegistrationState("error");
    setLineAuthControls(false, "LINEから開き直してください");
    return false;
  }

  if (recentlyAttemptedLiffLogin()) {
    setUserRegistrationState("error");
    setLineAuthControls(false, "再認証できませんでした");
    return false;
  }

  rememberLiffLoginAttempt();
  setLineAuthControls(false, "LINEへ再ログイン中...");
  if (liff.isLoggedIn()) {
    liff.logout();
  }
  liff.login({ redirectUri: liffLoginRedirectUrl() });
  return true;
}

function getLiffDebugContext() {
  return {
    href: window.location.href,
    origin: window.location.origin,
    pathname: window.location.pathname,
    search: window.location.search,
    requireLogin: window.REQUIRE_LIFF_LOGIN === true,
    hasLiff: Boolean(window.liff),
    inClient: Boolean(window.liff && liff.isInClient && liff.isInClient()),
    userAgent: navigator.userAgent,
  };
}

function getLineAuthForms() {
  return Array.from(document.querySelectorAll("form")).filter((form) => {
    return Boolean(form.querySelector('input[name="line_user_id"], input[name="user_id"], input[name="userid"]'));
  });
}

function setLineAuthControls(enabled, message = "") {
  getLineAuthForms().forEach((form) => {
    form.dataset.lineAuthReady = enabled ? "true" : "false";
    form.querySelectorAll('button[type="submit"], button:not([type])').forEach((button) => {
      if (!button.dataset.defaultLabel) {
        button.dataset.defaultLabel = button.textContent;
      }
      button.disabled = !enabled;
      button.textContent = enabled ? button.dataset.defaultLabel : (message || "LINE確認中...");
    });
  });
}

function hasLineAuthValues(form) {
  const userInput = form.querySelector('input[name="line_user_id"], input[name="user_id"], input[name="userid"]');
  const tokenInput = form.querySelector('input[name="id_token"], input[name="idToken"]');
  return Boolean(
    userInput
    && userInput.value
    && ((tokenInput && tokenInput.value) || window.LINE_SESSION_AUTHENTICATED === true)
  );
}

function setAllLineUserInputs(userId) {
  ["line_user_id", "user_id", "userid"].forEach((name) => {
    document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
      input.value = userId || "";
    });
  });
}

function setUserRegistrationState(state) {
  if (window.REQUIRE_USER_REGISTRATION !== true) {
    return;
  }

  const status = document.getElementById("user-registration-check-status");
  const prompt = document.getElementById("user-registration-required");
  const forms = document.querySelectorAll("form[data-requires-user-registration]");

  if (status) {
    status.hidden = state === "registered" || state === "unregistered";
    if (state === "error") {
      status.textContent = "マイページの登録状況を確認できませんでした。画面を再読み込みしてください。";
    }
  }
  if (prompt) {
    prompt.hidden = state !== "unregistered";
    if (state === "unregistered") {
      prompt.focus({ preventScroll: true });
    }
  }
  forms.forEach((form) => {
    form.hidden = state !== "registered";
  });
}

async function confirmUserRegistration(userId, idToken = "") {
  if (window.REQUIRE_USER_REGISTRATION !== true) {
    return true;
  }

  try {
    const headers = { "Accept": "application/json" };
    if (idToken) {
      headers["X-Line-ID-Token"] = idToken;
    }
    const response = await fetch(`/users/check/${encodeURIComponent(userId)}`, {
      method: "GET",
      headers,
      credentials: "same-origin",
    });
    const body = await response.json();

    if (response.ok && body.exists === true) {
      setUserRegistrationState("registered");
      return true;
    }
    if (response.ok) {
      setUserRegistrationState("unregistered");
      setLineAuthControls(false, "マイページ登録が必要です");
      return false;
    }
    if (response.status === 401) {
      restartLineAuthentication("registration check rejected ID token");
      return false;
    }
  } catch (error) {
    console.warn("Failed to check user registration:", error);
  }

  setUserRegistrationState("error");
  setLineAuthControls(false, "登録状況を確認できません");
  return false;
}

async function restoreLineSession() {
  try {
    const response = await fetch("/link/session", {
      method: "GET",
      headers: {
        "Accept": "application/json",
      },
      credentials: "same-origin",
    });
    const body = await response.json();
    if (response.ok && body.ok && body.line_user_id) {
      window.LINE_SESSION_AUTHENTICATED = true;
      window.LINE_USER_ID = body.line_user_id;
      setAllLineUserInputs(body.line_user_id);
      if (await confirmUserRegistration(body.line_user_id)) {
        setLineAuthControls(true);
      }
      return true;
    }
  } catch (error) {
    console.warn("Failed to restore LINE session:", error);
  }

  window.LINE_SESSION_AUTHENTICATED = false;
  return false;
}

function installLineAuthSubmitGuard() {
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!form || !form.matches("form") || !form.querySelector('input[name="line_user_id"], input[name="user_id"], input[name="userid"]')) {
      return;
    }
    if (!hasLineAuthValues(form)) {
      event.preventDefault();
      setLineAuthControls(false, "LINE認証が必要です");
      window.alert("LINEログインを確認できませんでした。LINE内で開き直してから操作してください。");
    }
  }, true);
}

function formatBytes(size) {
  if (!Number.isFinite(size)) {
    return "";
  }
  if (size >= 1024 * 1024) {
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

function renderImagePreview(input) {
  const maxImages = 6;
  const files = Array.from(input.files || []);
  let preview = input.nextElementSibling;
  if (!preview || !preview.classList.contains("image-preview")) {
    preview = document.createElement("div");
    preview.className = "image-preview";
    input.insertAdjacentElement("afterend", preview);
  }

  preview.innerHTML = "";
  const status = document.createElement("p");
  status.className = files.length > maxImages ? "image-preview__status is-error" : "image-preview__status";
  status.textContent = files.length
    ? `${files.length}/${maxImages}枚を選択中`
    : `画像は${maxImages}枚まで選択できます。`;
  preview.appendChild(status);

  if (files.length > maxImages) {
    input.value = "";
    status.textContent = `画像は${maxImages}枚までです。選び直してください。`;
    return;
  }

  const list = document.createElement("div");
  list.className = "image-preview__grid";
  preview.appendChild(list);

  files.forEach((file) => {
    const item = document.createElement("figure");
    item.className = "image-preview__item";

    const image = document.createElement("img");
    image.alt = file.name;
    image.src = URL.createObjectURL(file);
    image.addEventListener("load", () => URL.revokeObjectURL(image.src), { once: true });

    const caption = document.createElement("figcaption");
    caption.textContent = `${file.name} (${formatBytes(file.size)})`;

    item.appendChild(image);
    item.appendChild(caption);
    list.appendChild(item);
  });
}

function installImagePreviews() {
  document.querySelectorAll('input[type="file"][accept*="image"]').forEach((input) => {
    if (input.dataset.imagePreviewReady === "true") {
      return;
    }
    input.dataset.imagePreviewReady = "true";
    input.addEventListener("change", () => renderImagePreview(input));
    renderImagePreview(input);
  });
}

async function initializeLiff() {
  const liffId = window.LIFF_ID || "";
  console.log("LIFF initialization started. LIFF ID:", liffId);
  installLineAuthSubmitGuard();
  installImagePreviews();
  setLineAuthControls(false, "LINE確認中...");

  // Flaskテンプレート外で使う場合に備えて、LIFF ID未設定でもフォーム確認は可能にする
  if (!window.liff || !liffId || liffId.includes("{{")) {
    console.warn("LIFF is not configured or not available.");
    await logToServer("LIFF is not configured or not available.");
    if (await restoreLineSession()) {
      return;
    }
    setLineAuthControls(false, "LINEで開いてください");
    return;
  }

  try {
    await liff.init({ liffId });
    console.log("LIFF initialized successfully.");
    await logToServer("LIFF initialized successfully.");
    clearLegacyLiffReturnUrl();

    if (!liff.isLoggedIn()) {
      console.log("Not logged in.");
      await logToServer("Not logged in.");

      if (window.REQUIRE_LIFF_LOGIN === true) {
        console.log("Redirecting to LIFF login...");
        await logToServer("Redirecting to LIFF login.", getLiffDebugContext());
        restartLineAuthentication("LINE login required");
        return;
      }

      if (await restoreLineSession()) {
        return;
      }
      setLineAuthControls(false, "LINEログインが必要です");
      return;
    }

    console.log("User is logged in. Getting profile...");
    const profile = await liff.getProfile();
    const idToken = liff.getIDToken();
    window.LINE_ID_TOKEN = idToken || "";
    if (!hasFreshIdToken(window.LINE_ID_TOKEN)) {
      restartLineAuthentication("missing or expired ID token");
      return;
    }
    console.log("Profile retrieved.");
    await logToServer("Profile retrieved.");

    const lineUserIdInput = document.getElementById("line_user_id");
    const userIdInput = document.getElementById("user_id");
    const useridInput = document.getElementById("userid");
    const displayNameInput = document.getElementById("display_name");

    const setAllInputsByName = (name, value) => {
      document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
        input.value = value;
      });
    };

    const ensureIdTokenInputs = (value) => {
      document.querySelectorAll("form").forEach((form) => {
        let input = form.querySelector('input[name="id_token"]');
        if (!input) {
          input = document.createElement("input");
          input.type = "hidden";
          input.name = "id_token";
          form.appendChild(input);
        }
        input.value = value || "";
      });
    };

    console.log("Setting form values...");
    if (lineUserIdInput) {
      lineUserIdInput.value = profile.userId;
      console.log("line_user_id set.");
    } else {
      console.warn("line_user_id input not found");
      await logToServer("WARNING: line_user_id input not found");
    }

    if (userIdInput) {
      userIdInput.value = profile.userId;
    }

    if (useridInput) {
      useridInput.value = profile.userId;
    }

    window.LINE_USER_ID = profile.userId;
    setAllInputsByName("line_user_id", profile.userId);
    setAllInputsByName("user_id", profile.userId);
    setAllInputsByName("userid", profile.userId);
    setAllInputsByName("id_token", window.LINE_ID_TOKEN);
    ensureIdTokenInputs(window.LINE_ID_TOKEN);

    if (displayNameInput) {
      if (window.FILL_DISPLAY_NAME_FROM_LIFF === true && !displayNameInput.value.trim()) {
        displayNameInput.value = profile.displayName;
        console.log("display_name set.");
      } else if (window.FILL_DISPLAY_NAME_FROM_LIFF === true) {
        console.log("display_name already present.");
      }
    } else {
      console.warn("display_name input not found");
      await logToServer("WARNING: display_name input not found");
    }

    const linkResponse = await fetch("/link/liff", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        userId: profile.userId,
        idToken: window.LINE_ID_TOKEN,
      }),
      keepalive: true,
    });
    if (!linkResponse.ok) {
      if (linkResponse.status === 401) {
        restartLineAuthentication("server rejected ID token");
      } else {
        setUserRegistrationState("error");
        setLineAuthControls(false, "LINE認証を確認できません");
      }
      return;
    }

    window.LINE_SESSION_AUTHENTICATED = true;
    clearLiffLoginAttempt();
    if (!await confirmUserRegistration(profile.userId)) {
      return;
    }
    setLineAuthControls(true);
    console.log("LIFF link endpoint called successfully.");
    logToServer("LIFF link endpoint called successfully.");
    window.dispatchEvent(new Event("line-authenticated"));
  } catch (error) {
    console.error("LIFF initialization error:", error);
    await logToServer("LIFF initialization error: " + error.message);
  }
}

function logToServer(message, details = {}) {
  const payload = JSON.stringify({
    message: message,
    details: details,
    timestamp: new Date().toISOString(),
  });

  try {
    if (navigator.sendBeacon) {
      const sent = navigator.sendBeacon("/link/liff-debug", new Blob([payload], { type: "application/json" }));
      if (sent) {
        return;
      }
    }

    fetch("/link/liff-debug", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: payload,
      keepalive: true,
    }).catch((error) => {
      console.error("Failed to send debug log:", error);
    });
  } catch (e) {
    console.error("Failed to send debug log:", e);
  }
}

initializeLiff().catch((error) => {
  console.error("LIFF initialization failed:", error);
  logToServer("LIFF initialization failed: " + error.message);
});
