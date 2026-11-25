# agentdbg demo video

A 37-second Remotion film of what the tool does. Every line of terminal text in it is
output the tool actually produced while it was being built — nothing is invented.

```
npm install
npm run studio     # scrub through it at localhost:3000
npm run build      # -> out/agentdbg-demo.mp4
npm run gif        # -> out/agentdbg-demo.gif  (half size, every 2nd frame, for a README)
```

## The five beats

| # | Beat | The point |
|---|---|---|
| 1 | title | what it is, in four words |
| 2 | the problem | auto mode allowed a write outside the project; you find out later |
| 3 | **deny with a reason** | the agent freezes, you say why, it adapts instead of dying |
| 4 | **edit and resume** | fix the tool input mid-run — same session, context intact |
| 5 | guard, unattended | breakpoints fail open, deny rules fail closed |

Beats 3 and 4 are the ones to keep if you cut it down: a permission prompt can already
say no, but nothing else can *correct* a running agent.

## Editing it

`src/Video.tsx` is the script — one component per beat, `<Sequence>` sets when each starts,
and the `at={}` prop on every line is its frame offset within that beat. 30fps, so `at={60}`
is two seconds in. `src/ui.tsx` holds the palette and the four building blocks (`Pane`,
`Line`, `Type`, `Caption`); there is deliberately one entrance animation for everything, so
adding a beat can't introduce a fifth kind of motion.
