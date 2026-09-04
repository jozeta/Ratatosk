(function () {
  // Info-icon tooltips live inside scrollable/clipped containers (.table-wrap,
  // modals, etc.) and CSS position:absolute has no way to escape that - the
  // tooltip gets cut off or buried under later elements. Switching to
  // position:fixed with a JS-computed position, right before it's shown,
  // escapes any ancestor's overflow clipping and stacking context entirely.
  const MARGIN = 8;

  function reposition(icon) {
    const tip = icon.querySelector(".info-tooltip");
    if (!tip) return;
    const iconRect = icon.getBoundingClientRect();

    // Neutral placement first, so the next getBoundingClientRect() call
    // measures the tooltip's real (unclamped) size instead of stale values
    // left over from the last time it was shown somewhere else. The CSS rule
    // sets `bottom:135%` for the default (unpositioned) layout; leaving that
    // active while we also set an inline `top` over-constrains the box (both
    // top and bottom set with height:auto), which makes the browser stretch
    // the height to fit the gap between them instead of sizing to content -
    // clearing `bottom` here is what keeps height genuinely auto.
    tip.style.position = "fixed";
    tip.style.left = "0px";
    tip.style.top = "0px";
    tip.style.bottom = "auto";
    tip.style.transform = "none";
    const tipRect = tip.getBoundingClientRect();

    const halfWidth = tipRect.width / 2;
    const left = Math.min(
      Math.max(iconRect.left + iconRect.width / 2, halfWidth + MARGIN),
      window.innerWidth - halfWidth - MARGIN
    );

    // Flip below the icon when there isn't room above it (e.g. near the top
    // of the page) so the tooltip never runs off the top of the viewport.
    const showBelow = iconRect.top < tipRect.height + MARGIN * 2;
    tip.classList.toggle("tooltip-below", showBelow);
    tip.style.left = left + "px";
    if (showBelow) {
      tip.style.top = iconRect.bottom + MARGIN + "px";
      tip.style.transform = "translateX(-50%)";
    } else {
      tip.style.top = iconRect.top - MARGIN + "px";
      tip.style.transform = "translate(-50%, -100%)";
    }
  }

  document.addEventListener("mouseover", (e) => {
    const icon = e.target.closest(".info-icon");
    if (icon) reposition(icon);
  });
  document.addEventListener("focusin", (e) => {
    const icon = e.target.closest(".info-icon");
    if (icon) reposition(icon);
  });
})();
