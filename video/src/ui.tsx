import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export const C = {
  bg: '#0b0e14',
  glow: '#131926',
  pane: '#11151f',
  edge: '#232a3a',
  text: '#c9d4e5',
  dim: '#6b7889',
  green: '#7ee787',
  red: '#ff7b72',
  amber: '#e3b341',
  blue: '#79c0ff',
  violet: '#d2a8ff',
};

export const MONO = 'ui-monospace, "Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace';

/** Fade + lift, the only entrance used anywhere. One motion vocabulary, not five. */
export const Rise: React.FC<{at: number; children: React.ReactNode; style?: React.CSSProperties}> = ({
  at,
  children,
  style,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - at, fps, config: {damping: 200}});
  return (
    <div style={{...style, opacity: s, transform: `translateY(${interpolate(s, [0, 1], [14, 0])}px)`}}>
      {children}
    </div>
  );
};

export const Line: React.FC<{
  at: number;
  color?: string;
  indent?: number;
  bold?: boolean;
  size?: number;
  children: React.ReactNode;
}> = ({at, color = C.text, indent = 0, bold, size = 30, children}) => (
  <Rise at={at} style={{paddingLeft: indent * 26, whiteSpace: 'pre'}}>
    <span style={{color, fontFamily: MONO, fontSize: size, fontWeight: bold ? 700 : 400, lineHeight: 1.55}}>
      {children}
    </span>
  </Rise>
);

/** Types a line out, then holds a blinking block cursor. */
export const Type: React.FC<{at: number; text: string; color?: string; size?: number; cps?: number}> = ({
  at,
  text,
  color = C.text,
  size = 30,
  cps = 2.2,
}) => {
  const frame = useCurrentFrame();
  const elapsed = Math.max(0, frame - at);
  const shown = Math.min(text.length, Math.floor(elapsed * cps));
  const done = shown >= text.length;
  const blink = Math.floor(frame / 15) % 2 === 0;
  if (frame < at) return null;
  return (
    <div style={{fontFamily: MONO, fontSize: size, color, lineHeight: 1.55, whiteSpace: 'pre'}}>
      {text.slice(0, shown)}
      <span style={{opacity: done && !blink ? 0 : 1, color: C.violet}}>▌</span>
    </div>
  );
};

export const Pane: React.FC<{
  at: number;
  title: string;
  accent: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({at, title, accent, children, style}) => (
  <Rise
    at={at}
    style={{
      flex: 1,
      // Fixed height, not content height: lines fade in over the scene, and a pane that
      // grew with them would jitter on every new line.
      height: 620,
      background: C.pane,
      border: `1px solid ${C.edge}`,
      borderRadius: 14,
      overflow: 'hidden',
      boxShadow: '0 30px 80px rgba(0,0,0,0.45)',
      ...style,
    }}
  >
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '14px 20px',
        borderBottom: `1px solid ${C.edge}`,
        background: C.glow,
      }}
    >
      <div style={{width: 10, height: 10, borderRadius: 999, background: accent}} />
      <span style={{fontFamily: MONO, fontSize: 22, color: C.dim, letterSpacing: 0.4}}>{title}</span>
    </div>
    <div style={{padding: '22px 26px'}}>{children}</div>
  </Rise>
);

/** The one-line point of the scene, pinned to the bottom. */
export const Caption: React.FC<{at: number; children: React.ReactNode; accent?: string}> = ({
  at,
  children,
  accent = C.violet,
}) => (
  <Rise
    at={at}
    style={{position: 'absolute', bottom: 64, left: 0, right: 0, display: 'flex', justifyContent: 'center'}}
  >
    <div
      style={{
        fontFamily: MONO,
        fontSize: 34,
        color: C.text,
        borderLeft: `3px solid ${accent}`,
        paddingLeft: 20,
        letterSpacing: 0.2,
      }}
    >
      {children}
    </div>
  </Rise>
);

/** Pulsing badge used the moment the agent is actually frozen. */
export const Paused: React.FC<{at: number}> = ({at}) => {
  const frame = useCurrentFrame();
  if (frame < at) return null;
  const pulse = 0.55 + 0.45 * Math.sin((frame - at) / 5);
  return (
    <div
      style={{
        marginTop: 18,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 16px',
        borderRadius: 999,
        border: `1px solid ${C.amber}`,
        background: 'rgba(227,179,65,0.10)',
        opacity: pulse,
      }}
    >
      <span style={{fontFamily: MONO, fontSize: 24, color: C.amber}}>⏸ frozen — waiting for you</span>
    </div>
  );
};

export const Stage: React.FC<{children: React.ReactNode}> = ({children}) => (
  <div
    style={{
      position: 'absolute',
      inset: 0,
      background: `radial-gradient(1200px 700px at 50% -10%, ${C.glow}, ${C.bg})`,
      // The bottom band belongs to the caption alone - it was overlapping the panes.
      padding: '70px 110px 200px',
      display: 'flex',
      alignItems: 'center',
      gap: 40,
    }}
  >
    {children}
  </div>
);
