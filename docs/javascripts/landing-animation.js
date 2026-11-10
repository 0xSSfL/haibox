/* HAIBOX homepage motion control; no network requests, timers, or eval. */
(function () {
  'use strict';
  function init() {
    const landing = document.querySelector('.hb-landing');
    if (!landing || landing.dataset.motionReady === 'true') return;
    landing.dataset.motionReady = 'true';
    const button = landing.querySelector('.hb-motion-toggle');
    if (!button) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    function updatePreference() {
      button.hidden = reduced.matches;
      if (reduced.matches) {
        landing.classList.remove('hb-paused');
        button.setAttribute('aria-pressed', 'false');
        button.textContent = 'Pause animation';
      }
    }
    button.hidden = false;
    button.addEventListener('click', function () {
      const paused = landing.classList.toggle('hb-paused');
      button.setAttribute('aria-pressed', String(paused));
      button.textContent = paused ? 'Resume animation' : 'Pause animation';
    });
    if (typeof reduced.addEventListener === 'function') {
      reduced.addEventListener('change', updatePreference);
    }
    updatePreference();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
  if (typeof document$ !== 'undefined' && document$.subscribe) {
    document$.subscribe(init);
  }
}());
