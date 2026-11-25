import React from 'react';
import {Composition} from 'remotion';
import {Video} from './Video';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Demo"
    component={Video}
    durationInFrames={1110}
    fps={30}
    width={1920}
    height={1080}
  />
);
