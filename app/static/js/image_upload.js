(() => {
  'use strict';
  const optimized = new WeakSet();

  async function shrinkPhoto(file) {
    // Keep animation/transparency and already small images intact.
    if (file.type !== 'image/jpeg' || !/\.jpe?g$/i.test(file.name)
        || file.size <= 512 * 1024 || optimized.has(file)
        || typeof window.createImageBitmap !== 'function') return file;
    let bitmap, canvas;
    try {
      bitmap = await window.createImageBitmap(file, {imageOrientation: 'from-image'});
      const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
      canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.82));
      if (!blob || blob.type !== 'image/jpeg' || blob.size >= file.size) return file;
      const result = new File([blob], file.name, {type: 'image/jpeg', lastModified: file.lastModified});
      optimized.add(result);
      return result;
    } catch (_) {
      return file;
    } finally {
      bitmap?.close();
      if (canvas) { canvas.width = 0; canvas.height = 0; }
    }
  }

  window.preparePostImages = async form => {
    if (typeof DataTransfer !== 'function') return;
    for (const input of form.querySelectorAll('input[type="file"][accept*="image"]')) {
      if (input.disabled) continue;
      const originals = Array.from(input.files || []);
      if (!originals.length || originals.length > 6) continue;
      try {
        const transfer = new DataTransfer();
        // Process one photo at a time to bound memory usage on phones.
        for (const file of originals) transfer.items.add(await shrinkPhoto(file));
        const current = Array.from(input.files || []);
        if (current.length === originals.length && current.every((file, i) => file === originals[i])) {
          input.files = transfer.files;
        }
      } catch (_) { /* Unsupported file replacement: retain the original selection. */ }
    }
  };
})();
