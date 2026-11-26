import { lazy, memo, Suspense } from "react";

// Phase 6 code-splitting: the markdown pipeline (react-markdown, remark/rehype,
// visuals, the secure setup card) lives in MarkdownRenderer.jsx, a separate
// chunk. It starts downloading as soon as this module loads — in parallel with
// the shell's first paint — so by the time a reply renders it is normally ready.
// Until then the text shows as plain pre-wrapped prose, never blank.
const load = () => import("./MarkdownRenderer.jsx");
const Renderer = lazy(load);
load();

function Plain({ children }) {
  return <div className="md whitespace-pre-wrap">{children}</div>;
}

// Memoised on the source text: a re-render with the same markdown is free.
export default memo(function Markdown({ children }) {
  return (
    <Suspense fallback={<Plain>{children}</Plain>}>
      <Renderer>{children}</Renderer>
    </Suspense>
  );
}, (a, b) => a.children === b.children);
