// Switch to bundled SVGs only if the local icon fonts cannot load.
(async () => {
  if (!document.fonts) return;
  try {
    const fonts = await Promise.all([document.fonts.load('900 16px "Font Awesome 6 Free"'), document.fonts.load('400 16px "Font Awesome 6 Free"'), document.fonts.load('400 16px "Font Awesome 6 Brands"')]);
    if (fonts.some(group => !group.length)) throw new Error('Icon font unavailable');
  } catch { document.documentElement.classList.add('ft-icon-fallback'); }
})();
