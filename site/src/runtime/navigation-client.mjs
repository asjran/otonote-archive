import {installNavigationFeedback} from '../lib/navigation-feedback.mjs';
import {loadingArtFiles} from './loading-presentation.mjs';
import loadingCss from '../styles/loading-shell.css';
import transitionCss from '../styles/page-transitions.css';
import feedbackCss from '../styles/navigation-feedback.css';
const codeRoot=globalThis[Symbol.for('ournotes.code-root.v1')] || document.currentScript.dataset.codeRoot;
installNavigationFeedback({css:loadingCss+'\n'+transitionCss+'\n'+feedbackCss,
  art:Object.fromEntries(loadingArtFiles.map(file=>[file,new URL('loading/'+file,new URL(codeRoot,location.href)).href]))});
