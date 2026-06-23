function getCurrentPageLoginRedirectUri() {
  return window.location.origin + window.location.pathname;
}

function clearLegacyLiffReturnUrl() {
  try {
    window.localStorage.removeItem("erabu_zai_spot_liff_return_url");
  } catch (error) {
    console.warn("Failed to clear legacy LIFF return URL:", error);
  }
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
        await logToServer("Redirecting to LIFF login...");
        liff.login({ redirectUri: getCurrentPageLoginRedirectUri() });
      }

      return;
    }

    console.log("User is logged in. Getting profile...");
    const profile = await liff.getProfile();
    console.log("Profile retrieved:", profile);
    await logToServer("Profile retrieved: userId=" + profile.userId + ", displayName=" + profile.displayName);

    const lineUserIdInput = document.getElementById("line_user_id");
    const userIdInput = document.getElementById("user_id");
    const useridInput = document.getElementById("userid");
    const displayNameInput = document.getElementById("display_name");

    const setAllInputsByName = (name, value) => {
      document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
        input.value = value;
      });
    };

    console.log("Setting form values...");
    if (lineUserIdInput) {
      lineUserIdInput.value = profile.userId;
      console.log("line_user_id set to:", profile.userId);
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

    if (displayNameInput) {
      if (window.FILL_DISPLAY_NAME_FROM_LIFF === true && !displayNameInput.value.trim()) {
        displayNameInput.value = profile.displayName;
        console.log("display_name set to:", profile.displayName);
      } else if (window.FILL_DISPLAY_NAME_FROM_LIFF === true) {
        console.log("display_name already present, keeping current value:", displayNameInput.value);
      }
    } else {
      console.warn("display_name input not found");
      await logToServer("WARNING: display_name input not found");
    }

    await fetch("/link/liff", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        userId: profile.userId,
        displayName: profile.displayName,
        pictureUrl: profile.pictureUrl || "",
      }),
    });

    console.log("LIFF link endpoint called successfully.");
    await logToServer("LIFF link endpoint called successfully. userId=" + profile.userId);
  } catch (error) {
    console.error("LIFF initialization error:", error);
    await logToServer("LIFF initialization error: " + error.message);
  }
}

async function logToServer(message) {
  try {
    await fetch("/link/liff-debug", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: message,
        timestamp: new Date().toISOString(),
      }),
    });
  } catch (e) {
    console.error("Failed to send debug log:", e);
  }
}

initializeLiff().catch((error) => {
  console.error("LIFF initialization failed:", error);
  logToServer("LIFF initialization failed: " + error.message);
});
