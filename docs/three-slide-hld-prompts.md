# Dynamic Analyser - 3 Slide HLD (AST-Centric)

Use this file as a copy-paste guide to build a clean 3-slide deck.

---

## Slide 1 - Problem + Scope (What is built now)

### Slide title
`Dynamic Analyser: Current Scope`

### Put this text on slide
- We solve slow diagnosis in CI/CD and runtime logs.
- Current MVP supports:
  - CI/CD log analysis
  - Small application log analysis
  - Static code analysis
- Core design choice: AST parsing is the shared intelligence layer.

### Prompt to generate slide content (ChatGPT)
```text
Create concise content for a presentation slide titled "Dynamic Analyser: Current Scope".
Audience: engineering reviewers.
Keep it honest and MVP-focused.
Mention only:
1) CI/CD log analysis
2) Small application log analysis
3) Static code analysis
Emphasize that AST parsing is the central shared component.
Return:
- one subtitle (max 12 words)
- 4 bullet points (short)
- one closing line on business value.
```

### Diagram to make for this slide
**Diagram type:** Simple 3-box capability map  
**How to draw:**
- Left box: `CI/CD Logs`
- Middle box: `AST Parsing Core` (larger, highlighted)
- Right box: `App Logs + Static Analysis`
- Arrow from left -> middle and right -> middle
- Small footer label: `MVP: small logs + core analysis`

### Prompt to generate the diagram image
```text
Generate a simple architecture mini-diagram on white background.
Title: "MVP Scope - Dynamic Analyser"
Boxes:
1) CI/CD Logs (left)
2) AST Parsing Core (center, larger, highlighted)
3) App Logs + Static Analysis (right)
Arrows should point into AST Parsing Core.
Style: minimal, clean, presentation-ready, readable labels.
```

---

## Slide 2 - Core Architecture (Main Slide)

### Slide title
`Core Architecture - AST First`

### Put this text on slide
- All analysis modes pass through AST parsing and code indexing.
- CI/CD flow: GitHub -> logs parse -> AST mapping -> AI analysis.
- App flow: small logs + GitHub -> function mapping via AST -> AI analysis.
- Static flow: GitHub -> AST parse -> code-level analysis.

### Prompt to generate slide content (ChatGPT)
```text
Create content for one technical slide titled "Core Architecture - AST First".
Keep it simple and HLD-level only.
Include 4 bullets:
1) shared AST core
2) CI/CD flow
3) app log flow
4) static analysis flow
No deep implementation details, no hype language.
```

### Diagram to make for this slide
**Diagram type:** 3-lane HLD with shared center  
**How to draw:**
- Top lane (CI/CD): `GitHub -> CI/CD Log Parser -> AST Parsing -> AI Analysis`
- Middle lane (Application Logs): `App Logs + GitHub -> Log Parser -> Function Mapping -> AST Parsing -> AI Analysis`
- Bottom lane (Static): `GitHub -> AST Parsing -> Code-Level Analysis`
- Keep `AST Parsing` visually central and same color in every lane.

### Prompt to generate the diagram image
```text
Create a clean high-level architecture diagram (16:9) titled "Dynamic Analyser - Core AST Architecture".
Use 3 horizontal lanes:
1) CI/CD: GitHub -> CI/CD Log Parser -> AST Parsing -> AI Analysis
2) Application Logs: App Logs + GitHub -> Log Parser -> Function Mapping -> AST Parsing -> AI Analysis
3) Static Analysis: GitHub -> AST Parsing -> Code-Level Analysis
Make AST Parsing the visual center and same highlight color in all lanes.
Style: minimal, light background, clear arrows, readable text.
```

---

## Slide 3 - Output + Value

### Slide title
`What the System Produces`

### Put this text on slide
- Prioritized bottlenecks/issues from logs and code.
- Source-linked insights using AST/function mapping.
- AI-generated fix suggestions for faster triage.
- Result: reduced time to identify and start fixing problems.

### Prompt to generate slide content (ChatGPT)
```text
Write concise slide content for "What the System Produces".
Context: an AST-centric MVP analyzer with CI/CD logs, small app logs, and static analysis.
Return:
- 4 short bullets describing outputs
- 1 final impact line for developers.
Keep tone practical and engineering-focused.
```

### Diagram to make for this slide
**Diagram type:** Input -> Engine -> Output funnel  
**How to draw:**
- Inputs block: `CI/CD Logs`, `App Logs`, `GitHub Code`
- Center block (highlight): `AST Parsing + AI Analysis`
- Outputs block:
  - `Ranked Bottlenecks`
  - `Code-Level Findings`
  - `Fix Suggestions`
- Final arrow to small badge: `Faster Debugging`

### Prompt to generate the diagram image
```text
Generate a simple input-to-output architecture diagram titled "Dynamic Analyser Outputs".
Left (inputs): CI/CD Logs, App Logs, GitHub Code.
Center (highlight): AST Parsing + AI Analysis.
Right (outputs): Ranked Bottlenecks, Code-Level Findings, Fix Suggestions.
Add a final arrow to a small label: Faster Debugging.
Style: clean, minimal, slide-friendly, no clutter.
```

---

## Suggested visual consistency
- Use one accent color for AST (`purple`).
- Keep AI blocks in `blue`.
- Keep analysis inputs in `gray` and outputs in `green`.
- Use the same font and arrow style in all 3 slides.

