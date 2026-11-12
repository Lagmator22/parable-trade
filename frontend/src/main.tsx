import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './style.css';
import './forms.css';
import './market.css';
import './agent.css';
import './purchase.css';
import './ledger.css';
import './sell.css';
import './deals.css';

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
