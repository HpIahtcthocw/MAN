import {defineConfig} from 'vite';
export default defineConfig({root:'frontend',build:{outDir:'../web/dist',emptyOutDir:true,
 // This is a client-only SPA. Radix's RSC directives have no server boundary here.
 rolldownOptions:{onwarn(warning,defaultHandler){if(warning.code==='MODULE_LEVEL_DIRECTIVE')return;defaultHandler(warning)}}
},server:{port:5178,proxy:{'/api':'http://127.0.0.1:8770'}}});
