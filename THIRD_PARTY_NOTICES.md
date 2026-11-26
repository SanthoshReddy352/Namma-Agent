# Third-party notices

Namma Agent includes or adapts work from the projects below. Their licences are
reproduced here as they require. Dependencies installed by `pip` / `npm` carry their
own licence files and are not repeated here.

## Hermes Agent (Nous Research): MIT

Namma Agent's Phase 9 desktop redesign follows Hermes Agent's desktop layout and
interaction model: the titlebar band, the sidebar and profile rail, the side panel,
and the provider setup flow. `namma_agent/webui/src/haptics.js` ports Hermes'
`apps/desktop/src/lib/haptics.ts` and `haptics-provider.tsx`, so button clicks sound
exactly as they do in Hermes. Namma Agent keeps its own name, assistant name and art;
no Hermes branding is used.

```
MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## web-haptics (Lochie Axon): MIT

The click sounds come from `web-haptics` 0.0.6, the library Hermes Agent uses: an npm
dependency of the web UI (`namma_agent/webui/package.json`), MIT licensed,
Copyright (c) 2025 Lochie Axon.
