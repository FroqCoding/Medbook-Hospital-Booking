# MedBook Front-End Style Guide

This guide defines shared UI wording, capitalization, component classes, and spacing conventions for consistency across pages.

## 1. Brand & Voice
- Brand name: MedBook (capital M, capital B)
- Tone: Clear, concise, reassuring, professional.
- Avoid exclamation marks unless critical feedback.

## 2. Canonical Auth Phrasing
| Context | Use |
|---------|-----|
| Action button | "Log in" / "Sign up" |
| Toggle link | "Already have an account? Log in" |
| Doctor alt toggle | "Are you a doctor? Sign up" |
| Status / requirement | "You need to log in to book an appointment." |
| Toast after signup | "Account created. Log in to continue." |

Do NOT use: Login, Sign-in, Sign-in (as verb). Keep provider buttons: "Sign in with Google" / "Sign in with Apple" (industry-standard phrasing retained intentionally).

## 3. Typography Scale (Utility Classes)
| Token | Definition |
|-------|------------|
| .h1 | Section / page hero headings |
| .h2 | Major subsection headings |
| .h3 | Minor subsection / card titles |
| .lead | Larger supporting paragraph |
| .small | Subtext / meta info |

Prefer semantic HTML (h1-h3, p) plus these classes for visual consistency.

## 4. Buttons
Use semantic utility classes from `style.css`:
- Primary: `btn btn-primary`
- Secondary: `btn btn-secondary`
- Danger: `btn btn-danger`
- Ghost/minimal: `btn btn-ghost`
- Full width: add `full-width`
- Size variants: append `btn-sm` or `btn-lg`

Example:
```html
<button class="btn btn-primary">Log in</button>
<a href="#" class="btn btn-secondary btn-sm">Cancel</a>
```

## 5. Form Elements
Wrap label + input groups vertically with 0.5–0.75rem spacing.
- Inputs: class `input`
- Labels: class `label` (optional if native label styling OK)
- Help text: `help-text`
- Error: add `input-error` and show inline message with `.small` or `help-text` styled red.

Example:
```html
<label for="email" class="label">Email</label>
<input id="email" type="email" class="input" />
<p class="help-text">We never share your email.</p>
```

## 6. Spacing & Layout
- Outer page max width: `max-w-7xl` (keep via Tailwind) or for auth flows: centered with `auth-panel`.
- Vertical section spacing: 2.5–3rem (`py-10` / `py-12`).
- Internal card padding: use `.card` + `.card-section` wrappers.

## 7. Navigation
Active nav item adds `nav-link active`. Inactive ones: `nav-link`.

Example:
```html
<nav class="navbar">
  <a href="index.html" class="nav-link active">Home</a>
  <a href="doctors.html" class="nav-link">Doctors</a>
</nav>
```

## 8. Toasts & Feedback
Use `.toast` JS-injected element. Show for 2–3 seconds. Wording pattern: concise sentence, no trailing period if <= 3 words.

Examples:
- "Saved"
- "Profile updated"
- "Booking canceled"

## 9. Accessibility
- Always pair inputs with `<label>`.
- Use `aria-live="polite"` for dynamic error or toast regions if persistent.
- Ensure color contrast ratio ≥ 4.5:1 for text.

## 10. File / Asset Conventions
- Shared visual tokens: keep in `style.css` only.
- Avoid embedding long inline styles; prefer classes.
- New components: extend via additive class names, not altering core utility names.

## 11. Future Enhancements (Deferred)
- Dark mode token set.
- Extract Tailwind config for custom theme build instead of CDN version.
- Componentizing repeated nav with server-side includes or JS injection.

---
This guide should evolve. Propose edits PR-first.
