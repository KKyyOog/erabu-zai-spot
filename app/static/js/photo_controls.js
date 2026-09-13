(() => {
  'use strict';
  // Detail photos remain swipeable, with visible buttons for the same action.
  document.querySelectorAll('.detail-carousel, .listing-detail-modal .image-carousel').forEach((gallery, number) => {
    const photos = Array.from(gallery.querySelectorAll('img'));
    if (photos.length < 2) return;
    if (!gallery.id) gallery.id = `detail-photos-${number}`;
    const controls = document.createElement('div');
    controls.className = 'photo-controls';
    const previous = document.createElement('button');
    const next = document.createElement('button');
    const count = document.createElement('span');
    count.setAttribute('role', 'status');
    count.setAttribute('aria-live', 'polite');
    for (const button of [previous, next]) {
      button.type = 'button';
      button.className = 'secondary-button';
      button.setAttribute('aria-controls', gallery.id);
    }
    previous.textContent = '前の写真';
    next.textContent = '次の写真';
    let index = 0;
    const update = () => {
      const left = gallery.getBoundingClientRect().left;
      const distances = photos.map(photo => Math.abs(photo.getBoundingClientRect().left - left));
      index = distances.indexOf(Math.min(...distances));
      count.textContent = `${index + 1} / ${photos.length}枚`;
      previous.disabled = index === 0;
      next.disabled = index === photos.length - 1;
    };
    const move = direction => {
      const target = Math.max(0, Math.min(photos.length - 1, index + direction));
      gallery.scrollTo({left: gallery.scrollLeft + photos[target].getBoundingClientRect().left - gallery.getBoundingClientRect().left, behavior: 'instant'});
      update();
    };
    previous.addEventListener('click', () => move(-1));
    next.addEventListener('click', () => move(1));
    gallery.addEventListener('scroll', update, {passive: true});
    if (window.ResizeObserver) new ResizeObserver(update).observe(gallery);
    controls.append(previous, count, next);
    (gallery.closest('.listing-card__image') || gallery).insertAdjacentElement('afterend', controls);
    update();
  });
})();
