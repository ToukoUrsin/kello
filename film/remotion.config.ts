import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(95);
// captures, audio and renders live outside the repo (see README.md)
Config.setPublicDir(process.env.KELLO_FILM_OUT ? `${process.env.KELLO_FILM_OUT}/public` : 'out/public');
