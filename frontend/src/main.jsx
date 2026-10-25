import React from 'react';
import {createRoot} from 'react-dom/client';
import {Theme} from '@radix-ui/themes';
import '@radix-ui/themes/styles.css';
import './xiaoman.css';
import App from './Xiaoman.jsx';
createRoot(document.getElementById('root')).render(<App/>);
