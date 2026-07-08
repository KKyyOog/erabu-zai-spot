function clearLegacyLiffReturnUrl() {
  try {
    window.localStorage.removeItem("erabu_zai_spot_liff_return_url");
  } catch (error) {
    console.warn("Failed to clear legacy LIFF return URL:", error);
  }
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

async function initializeLiff() {
  const liffId = window.LIFF_ID || "";
  console.log("LIFF initialization started. LIFF ID:", liffId);

  // Flaskテンプレート外で使う場合に備えて、LIFF ID未設定でもフォーム確認は可能にする
  if (!window.liff || !liffId || liffId.includes("{{")) {
    console.warn("LIFF is not configured or not available.");
    await logToServer("LIFF is not configured or not available.");
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
        await logToServer("Redirecting to LIFF login without redirectUri.", getLiffDebugContext());
        liff.login();
      }

      return;
    }

    console.log("User is logged in. Getting profile...");
    const profile = await liff.getProfile();
    const idToken = liff.getIDToken();
    window.LINE_ID_TOKEN = idToken || "";
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

    fetch("/link/liff", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        userId: profile.userId,
        idToken: window.LINE_ID_TOKEN,
      }),
      keepalive: true,
    })
      .then(() => {
        console.log("LIFF link endpoint called successfully.");
        logToServer("LIFF link endpoint called successfully.");
        window.dispatchEvent(new Event("line-authenticated"));
      })
      .catch((error) => {
        console.warn("LIFF link endpoint failed:", error);
        logToServer("LIFF link endpoint failed: " + error.message);
      });
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
