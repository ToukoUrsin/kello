import React from 'react';
import {Composition} from 'remotion';
import {Film} from './Film';
import {FPS, TOTAL} from './timeline';
import {H, W} from './theme';

export const Root: React.FC = () => (
	<>
		<Composition id="Kello" component={Film} durationInFrames={TOTAL} fps={FPS} width={W} height={H} defaultProps={{audio: true, captions: true, music: true}} />
	</>
);
