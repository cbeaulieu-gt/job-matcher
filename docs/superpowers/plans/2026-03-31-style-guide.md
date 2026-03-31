# Plan: Write `docs/STYLE_GUIDE.md`

## Context
The project has a well-developed design language (dark industrial terminal-ledger aesthetic, amber accent, monospaced metadata) but it lives only as a one-line comment at the top of `static/style.css`. Anyone adding new UI has to reverse-engineer conventions from the existing CSS. A formal style guide makes the system explicit and consistent.

## Goal
Write `docs/STYLE_GUIDE.md` — a practical reference document that a developer can open when building new UI components. It should document what already exists, not invent new patterns.

## File to create
`I:\Web Development\job_matcher\docs\STYLE_GUIDE.md`

## Document structure

### 1. Design Philosophy (2–3 sentences)
Capture the stated aesthetic: "industrial terminal-ledger — near-black ground, amber accent, monospaced metadata, score tiers as rack status indicators."

### 2. Design Tokens
All CSS custom properties from `:root` in `static/style.css`, grouped by purpose:
- **Backgrounds** — `--bg-base`, `--bg-surface`, `--bg-raised`, `--bg-hover`
- **Borders** — `--border-subtle`, `--border-mid`, `--border-strong`
- **Text** — `--text-primary`, `--text-secondary`, `--text-muted`, `--text-accent` (#f5a623 amber)
- **Score tiers** — high/mid/low/null bg+text+border triplets
- **Skill chips** — match/miss bg+text+border triplets
- **Card accents** — `--accent-high/mid/low/null` (left-border colors)
- **Buttons** — `--btn-bg`, `--btn-hover`, `--btn-border`
- **Typography** — `--font-body` (serif), `--font-mono`, `--font-ui` (sans)
- **Layout** — `--max-width: 860px`, `--radius-sm/md/lg`

### 3. Typography
Table: context → font stack → size → weight → letter-spacing
- Page/section headings → `--font-mono`, 0.72rem, uppercase
- Provider/card titles → `--font-ui`, 0.93–0.95rem, weight 600
- Body text → `--font-body` (serif)
- Labels & metadata → `--font-mono`, 0.68–0.76rem, uppercase where labeling
- Stats/values → `--font-mono`, 1.55rem, `--text-accent`

### 4. Color Usage Matrix
When to use which tier color set — table mapping context → bg/text/border variables:
- Success/configured/matched/remote → `--score-high-*` (green)
- Warning/mid-score/setup alert → `--score-mid-*` (golden)
- Error/low-score/missing → `--score-low-*` (red)
- Neutral/unscored/not-set → `--score-null-*` / `--bg-raised` + `--text-muted`
- Accent/interactive → `--text-accent` (#f5a623)

### 5. Components
For each component: class name(s), intended HTML element, brief description, and the CSS variables it uses. No code blocks needed — the class names are the reference. Grouped by category:

**Layout**
- `.page-wrap` — page container, max-width 860px
- `.card-list` — flex column, gap 16px

**Navigation**
- `.site-header`, `.site-logo`, `.site-nav`, `.nav-tab` (+ `.active`)

**Cards (collapsible)**
- `.card-details[data-tier]`, `.card-summary`, `.summary-main`, `.summary-title`, `.summary-meta`, `.card-body`
- Tiers set via `data-tier="high|mid|low|null"` on `.card-details`

**Badges & Pills** (all use border-radius 20px, `--font-mono`, 0.65–0.72rem)
- `.score-badge[.tier-*]`, `.score-badge--sm[.tier-*]`
- `.badge-remote`, `.badge-onsite`, `.badge-jobtype`, `.model-badge`
- `.key-status[.configured|.not-set]`
- `.validation-badge[.validation-valid|invalid|warning|muted]`
- `.chip[.matched|.missing]`

**Buttons**
- `.btn` (base), `.btn-view`, `.btn-bookmark[.bookmarked]`, `.btn-apply[.applied]`, `.btn-dismiss`, `.btn-save`, `.btn-ingest`, `.btn-validate`

**Forms / Settings**
- `.settings-form`, `.provider-row`, `.provider-header`, `.provider-name`
- `.settings-label`, `.settings-input`
- `.filter-input`, `.filter-select`, `.filter-toggle`

**Toggle Switch** (new in PR #167)
- `.source-toggle` > `.source-toggle-track` > `.source-toggle-knob`
- Hidden checkbox controls state; CSS `:checked` transitions track amber + knob right

**Tabs** (Settings page)
- `.settings-tabs`, `.settings-tab-btn[.active]`, `.tab-pane[.active]`

**Notices / Alerts**
- `.save-notice` (green, auto-fade), `.save-error` (red), `.setup-banner` (amber)

**Empty State**
- `.empty-state`, `.empty-state-icon`, `.empty-state-title`, `.empty-state-body`

**Stats**
- `.stats-summary`, `.stat-box`, `.stat-value`, `.stat-label`, `.stats-table`

### 6. State Conventions
- Hover: slight background lift + border color increase
- Focus: `--border-strong`, color `--text-primary`; `:focus-visible` outline in `--text-accent` for custom controls
- Active/selected: use `--text-accent` or tier accent color
- Disabled/loading: `opacity: 0.5`, `pointer-events: none`
- Filled form field (non-placeholder): amber tint (`#1e1500` bg, `#5a3a00` border)

### 7. Rules for New Components
Short list of conventions to follow when adding new UI:
1. Use CSS custom properties — never hard-code hex values
2. "Positive" states (success, configured, remote) use `--score-high-*`
3. Pill/badge shape: `border-radius: 20px`, `--font-mono`, `0.65–0.72rem`
4. All custom interactive controls need `:focus-visible` with `--text-accent` outline
5. Font for labels/metadata: `--font-mono` uppercase; body copy: `--font-body`
6. Forms: max-width 600px, flex-column gap 16px

## Source file (read-only reference)
`I:\Web Development\job_matcher\static\style.css`

## Verification
- Open `docs/STYLE_GUIDE.md` and confirm all sections are present and readable
- No code changes needed — this is documentation only
- No tests to run
