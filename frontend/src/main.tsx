import React from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import App from './App';
import './styles.css';
// Plotly's async geography initialization is not compatible with development
// StrictMode's simulated mount/purge/remount cycle. Use the normal production
// lifecycle in development as well, so map rendering follows the same path.
createRoot(document.getElementById('root')!).render(<BrowserRouter><App/></BrowserRouter>);
