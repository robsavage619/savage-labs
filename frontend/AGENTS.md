<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Mandatory: every button has a satisfying, futuristic response

This is enforced globally — do not reimplement per-button. The visual press/hover/
focus states live in `app/globals.css` (`button:not(:disabled):not(.no-tactile)`),
and the synth "tick" + haptic + accent ripple are driven by
`components/tactile-feedback.tsx` (mounted once in `app/layout.tsx`).

Use a real `<button>` (or `role="button"`) and it inherits the feedback automatically.
Only suppress it with the class `no-tactile`, and only when there's a clear reason.
Never strip the global feedback or add a button that bypasses it.
