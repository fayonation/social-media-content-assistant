function initCopyCaption() {
  const btn = document.getElementById("copy-caption");
  const feedback = document.getElementById("copy-feedback");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const src = document.getElementById("caption-copy-src");
    const text = src ? src.value : "";
    try {
      await navigator.clipboard.writeText(text);
      if (feedback) {
        feedback.hidden = false;
        setTimeout(() => { feedback.hidden = true; }, 2000);
      }
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      if (feedback) {
        feedback.hidden = false;
        setTimeout(() => { feedback.hidden = true; }, 2000);
      }
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initCopyCaption();
});
