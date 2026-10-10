import React from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import {Workspace} from './Workspace';

createRoot(document.getElementById('root')!).render(<Workspace/>);
