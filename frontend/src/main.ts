import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';
import './lib/installieren.svelte';
import { themaStarten } from './lib/thema.svelte';

themaStarten();

const app = mount(App, { target: document.getElementById('app')! });

if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

export default app;
