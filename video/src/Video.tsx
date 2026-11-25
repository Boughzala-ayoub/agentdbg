import React from 'react';
import {AbsoluteFill, Sequence, interpolate, useCurrentFrame} from 'remotion';
import {C, Caption, Line, MONO, Pane, Paused, Rise, Stage, Type} from './ui';

/* Every line below is text this tool actually produced while it was being built. */

const Title: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(1000px 600px at 50% 40%, ${C.glow}, ${C.bg})`,
        justifyContent: 'center',
        alignItems: 'center',
      }}
    >
      <Rise at={0}>
        <div style={{fontFamily: MONO, fontSize: 120, color: C.text, letterSpacing: -2}}>
          agentdbg
        </div>
      </Rise>
      <Rise at={12}>
        <div style={{fontFamily: MONO, fontSize: 42, color: C.violet, marginTop: 18}}>
          breakpoints for a running agent
        </div>
      </Rise>
      <Rise at={26}>
        <div style={{fontFamily: MONO, fontSize: 30, color: C.dim, marginTop: 46}}>
          pause it · correct it · let it keep going
        </div>
      </Rise>
      <div
        style={{
          position: 'absolute',
          bottom: 120,
          width: 260,
          height: 2,
          background: C.violet,
          opacity: interpolate(frame, [30, 55], [0, 0.7], {extrapolateRight: 'clamp'}),
          transform: `scaleX(${interpolate(frame, [30, 60], [0, 1], {extrapolateRight: 'clamp'})})`,
        }}
      />
    </AbsoluteFill>
  );
};

const Problem: React.FC = () => (
  <Stage>
    <Pane at={0} title="claude — auto mode" accent={C.green}>
      <Type at={8} text="› write a file to C:\tmp\outside.md" color={C.text} />
      <div style={{height: 14}} />
      <Line at={46} color={C.green}>● Write(C:\tmp\outside.md)</Line>
      <Line at={54} color={C.dim} indent={1}>└ Wrote 3 lines to ..\..\..\tmp\outside.md</Line>
      <Line at={62} color={C.amber} indent={1}>└ Allowed by auto mode classifier</Line>
      <div style={{height: 14}} />
      <Line at={76} color={C.dim}>● Written — C:\tmp\outside.md (outside the working dir).</Line>
    </Pane>
    <Caption at={96} accent={C.amber}>the agent already did it. you find out later.</Caption>
  </Stage>
);

const Deny: React.FC = () => (
  <Stage>
    <Pane at={0} title="claude — auto mode" accent={C.green}>
      <Type at={20} text="› write a file to C:\tmp\outside1.md" />
      <div style={{height: 14}} />
      <Line at={58} color={C.dim}>● Write(C:\tmp\outside1.md)</Line>
      <Paused at={66} />
      <div style={{height: 18}} />
      <Line at={150} color={C.red}>✕ Error: don't write outside project dir</Line>
      <div style={{height: 12}} />
      <Line at={162} color={C.text}>● Blocked by a hook.</Line>
      <Line at={172} color={C.dim}>  Want it at …\agentdbg\outside1.md instead?</Line>
    </Pane>

    <Pane at={6} title="agentdbg attach" accent={C.violet} style={{maxWidth: 720}}>
      <Line at={10} color={C.dim} size={26}>$ agentdbg break "Write:!agentdbg"</Line>
      <Line at={16} color={C.green} size={26}>breakpoint 1 armed</Line>
      <div style={{height: 26}} />
      <Line at={70} color={C.text} bold>Write  C:/tmp/outside1.md</Line>
      <div style={{height: 10}} />
      <Line at={82} color={C.dim} size={26}>[c]ontinue [d]eny+why [e]dit [s]tep ›</Line>
      <div style={{height: 16}} />
      <Type at={100} text="d" color={C.red} size={30} cps={1} />
      <Type at={116} text="tell it why: don't write outside project dir" color={C.text} size={26} cps={1.6} />
    </Pane>

    <Caption at={186}>deny with a reason — it adapts instead of dying</Caption>
  </Stage>
);

const Edit: React.FC = () => (
  <Stage>
    <Pane at={0} title="agentdbg attach" accent={C.violet} style={{maxWidth: 760}}>
      <Line at={6} color={C.text} bold>Write  C:/tmp/thing.md</Line>
      <div style={{height: 10}} />
      <Line at={12} color={C.dim} size={26}>[c]ontinue [d]eny+why [e]dit [s]tep ›</Line>
      <div style={{height: 14}} />
      <Type at={24} text="e" color={C.blue} cps={1} />
      <div style={{height: 20}} />
      <Line at={44} color={C.dim} size={26}>{'{'}</Line>
      <Line at={48} color={C.red} size={26} indent={1}>- "file_path": "C:/tmp/thing.md",</Line>
      <Line at={64} color={C.green} size={26} indent={1}>+ "file_path": "…/agentdbg/thing.md",</Line>
      <Line at={72} color={C.dim} size={26} indent={1}>  "content": "…"</Line>
      <Line at={76} color={C.dim} size={26}>{'}'}</Line>
      <div style={{height: 18}} />
      <Line at={92} color={C.violet} size={26}>→ updatedInput sent, run continues</Line>
    </Pane>

    <Pane at={0} title="claude — same session, never restarted" accent={C.green}>
      <Line at={4} color={C.dim}>● Write(C:\tmp\thing.md)</Line>
      <Paused at={8} />
      <div style={{height: 20}} />
      <Line at={106} color={C.green}>● Write(…\agentdbg\thing.md)</Line>
      <Line at={114} color={C.dim} indent={1}>└ Wrote 3 lines</Line>
      <div style={{height: 14}} />
      <Line at={126} color={C.text}>● Done.</Line>
    </Pane>

    <Caption at={140} accent={C.blue}>edit the tool input mid-run — context intact</Caption>
  </Stage>
);

const Guard: React.FC = () => (
  <Stage>
    <Pane at={0} title="nobody watching — console detached" accent={C.amber} style={{maxWidth: 720}}>
      <Line at={6} color={C.dim} size={26}>$ agentdbg guard</Line>
      <Line at={14} color={C.green} size={26}>guarded: 2 deny rules, 2 breakpoints</Line>
      <div style={{height: 22}} />
      <Line at={26} color={C.dim} size={24}>deny 1. Bash:rm -rf |mkfs|dd if=</Line>
      <Line at={32} color={C.dim} size={24}>deny 2. Bash:git push .*--force</Line>
      <Line at={38} color={C.dim} size={24}>break 1. Write|Edit:!…/agentdbg</Line>
      <div style={{height: 22}} />
      <Line at={50} color={C.amber} size={26}>attached: False</Line>
      <Line at={58} color={C.text} size={26}>breakpoints fail open ↑</Line>
      <Line at={66} color={C.text} size={26}>deny rules fail closed ↓</Line>
    </Pane>

    <Pane at={0} title="claude — running unattended" accent={C.green}>
      <Type at={20} text="› clean up the temp dir" />
      <div style={{height: 16}} />
      <Line at={54} color={C.dim}>● Bash(rm -rf /important)</Line>
      <div style={{height: 12}} />
      <Line at={72} color={C.red} indent={1}>
        ✕ destructive shell command — do it yourself
      </Line>
      <Line at={80} color={C.red} indent={1}>  if you really mean it</Line>
      <div style={{height: 18}} />
      <Line at={96} color={C.dim}>● I can't remove that. Which paths did you mean?</Line>
      <div style={{height: 20}} />
      <Line at={112} color={C.green}>● Bash(ls -la)  → straight through</Line>
    </Pane>

    <Caption at={128} accent={C.red}>policy holds with nobody watching</Caption>
  </Stage>
);

const Outro: React.FC = () => (
  <AbsoluteFill
    style={{
      background: `radial-gradient(1000px 600px at 50% 45%, ${C.glow}, ${C.bg})`,
      justifyContent: 'center',
      alignItems: 'center',
      gap: 22,
    }}
  >
    <Rise at={0}>
      <div style={{fontFamily: MONO, fontSize: 40, color: C.text}}>a PreToolUse hook, one file, stdlib only</div>
    </Rise>
    <Rise at={10}>
      <div style={{fontFamily: MONO, fontSize: 30, color: C.dim, marginTop: 8}}>
        windows · macos · linux
      </div>
    </Rise>
    <Rise at={22}>
      <div
        style={{
          marginTop: 40,
          padding: '20px 34px',
          border: `1px solid ${C.edge}`,
          borderRadius: 12,
          background: C.pane,
          fontFamily: MONO,
          fontSize: 30,
          color: C.green,
        }}
      >
        agentdbg guard && agentdbg attach
      </div>
    </Rise>
    <Rise at={36}>
      <div style={{fontFamily: MONO, fontSize: 26, color: C.dim, marginTop: 34}}>
        no console attached? zero pauses, 60ms, nothing changes.
      </div>
    </Rise>
  </AbsoluteFill>
);

export const Video: React.FC = () => (
  <AbsoluteFill style={{background: C.bg}}>
    <Sequence durationInFrames={120}>
      <Title />
    </Sequence>
    <Sequence from={120} durationInFrames={150}>
      <Problem />
    </Sequence>
    <Sequence from={270} durationInFrames={260}>
      <Deny />
    </Sequence>
    <Sequence from={530} durationInFrames={210}>
      <Edit />
    </Sequence>
    <Sequence from={740} durationInFrames={220}>
      <Guard />
    </Sequence>
    <Sequence from={960} durationInFrames={150}>
      <Outro />
    </Sequence>
  </AbsoluteFill>
);
