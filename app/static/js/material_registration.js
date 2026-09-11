(function () {
  const root = document.querySelector('[data-location-choice]');
  if (!root) return;

  const locationInput = root.querySelector('input[name="location"]');
  const customPanel = root.querySelector('[data-custom-location-panel]');
  const customInput = root.querySelector('[data-custom-location]');
  const profileLabel = root.querySelector('[data-profile-location-label]');
  let profileLocation = (root.dataset.profileLocation || '').trim();
  let loadingProfile = false;

  function selectedSource() {
    return root.querySelector('input[name="location_source"]:checked')?.value || 'profile';
  }

  function updateLocationState() {
    const usesCustomLocation = selectedSource() === 'custom';
    customPanel.hidden = !usesCustomLocation;
    customInput.required = usesCustomLocation;
    locationInput.value = usesCustomLocation ? customInput.value.trim() : profileLocation;
  }

  function formatProfileLocation(user) {
    const area = String(user?.area || '').trim();
    const address = String(user?.address || '').trim();
    if (!address) return area;
    if (!area || address.includes(area)) return address;
    return `${area} ${address}`;
  }

  async function loadProfileLocation(userId) {
    if (!userId || loadingProfile) return;
    loadingProfile = true;
    try {
      const response = await fetch('/users/me/data', {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          'X-CSRF-Token': window.CSRF_TOKEN || '',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ userId, scope: 'profile' }),
      });
      const body = await response.json();
      if (response.ok && body.ok && body.exists) {
        profileLocation = formatProfileLocation(body.user);
      }
    } catch (error) {
      console.warn('Failed to load the registered base location:', error);
    } finally {
      loadingProfile = false;
      profileLabel.textContent = profileLocation || '拠点情報が未登録です';
      updateLocationState();
    }
  }

  root.querySelectorAll('input[name="location_source"]').forEach((radio) => {
    radio.addEventListener('change', updateLocationState);
  });
  customInput.addEventListener('input', updateLocationState);

  root.closest('form')?.addEventListener('submit', (event) => {
    updateLocationState();
    let error = root.querySelector('[data-location-error]');
    if (error) error.remove();
    if (!locationInput.value) {
      event.preventDefault();
      error = document.createElement('p');
      error.dataset.locationError = 'true';
      error.className = 'field-error';
      error.setAttribute('role', 'alert');
      error.textContent = selectedSource() === 'profile'
        ? 'マイページの拠点情報を登録するか、別の受け渡し場所を入力してください。'
        : '受け渡し場所を入力してください。';
      root.append(error);
      root.querySelector('input[name="location_source"]:checked')?.focus();
    }
  });

  window.addEventListener('user-registration-confirmed', (event) => {
    if (event.detail?.profileLocation) {
      profileLocation = formatProfileLocation(event.detail.profileLocation);
      profileLabel.textContent = profileLocation || '拠点情報が未登録です';
      updateLocationState();
      return;
    }
    loadProfileLocation(event.detail?.userId || window.LINE_USER_ID || '');
  });

  profileLabel.textContent = profileLocation || '拠点情報を読み込んでいます…';
  updateLocationState();
  if (window.LINE_USER_ID) loadProfileLocation(window.LINE_USER_ID);
})();
