import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { recordLearningQuiz } from "../api.js";
import Markdown from "./Markdown.jsx";

// Inline markdown for option labels: a button may only hold inline content, so we
// flatten paragraphs to a fragment and keep just inline code styling. This lets an
// option like `True` or `int` render as code without invalid <p>/<pre>-in-<button>.
const INLINE_MD = {
  p: ({ children }) => <>{children}</>,
  code: ({ children }) => (
    <code className="px-1 py-0.5 rounded bg-paper-sink dark:bg-night-soft font-mono text-[12.5px]">{children}</code>
  ),
};
const InlineMd = ({ children }) => (
  <ReactMarkdown remarkPlugins={[remarkGfm]} components={INLINE_MD}>{children || ""}</ReactMarkdown>
);

// An interactive multiple-choice check posed by the teacher agent (`pose_quiz`).
// Picking an option reveals correct/incorrect + an explanation, records the
// result (insights / understanding score), and — via onAnswered — hands the
// result back to the teacher so the lesson CONTINUES instead of stalling.
export default function QuizCard({ quiz, onAnswered }) {
  const { question, code = "", options = [], answer_index = 0, explanation = "",
          topic_id, module_id, quiz_id } = quiz || {};
  // `quiz.picked` is set when a previously-answered card is restored from
  // history — the card reopens already answered, exactly as it was left.
  const [picked, setPicked] = useState(quiz?.picked ?? null);
  const answered = picked !== null && picked !== undefined;

  async function choose(i) {
    if (answered) return;
    setPicked(i);
    const correct = i === answer_index;
    if (topic_id) {
      await recordLearningQuiz(topic_id, {
        question, correct, module_id, user_answer: String(options[i] ?? ""),
        quiz_id, options, answer_index, picked_index: i, explanation,
      });
    }
    onAnswered?.(quiz, { correct, picked: String(options[i] ?? "") });
  }

  return (
    <div className="flex gap-3 animate-rise">
      <div className="mt-0.5 h-7 w-7 shrink-0 grid place-items-center text-brand-deep">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .8-1 1.7" /><path d="M12 17h.01" /></svg>
      </div>
      <div className="flex-1 min-w-0 rounded-2xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel p-4">
        <div className="text-[11px] uppercase tracking-wider text-ink-faint dark:text-night-faint mb-1.5">Quick check</div>
        {/* Question (and any code it embeds) renders as markdown. */}
        <div className="font-medium text-[15px] mb-2 md-question"><Markdown>{question}</Markdown></div>
        {/* The dedicated code slot — shown as a code block so the learner can read
            the snippet the question asks about. */}
        {code ? <div className="mb-3"><Markdown>{"```\n" + code + "\n```"}</Markdown></div> : null}
        <div className="space-y-1.5">
          {options.map((opt, i) => {
            const isAnswer = i === answer_index;
            const isPicked = i === picked;
            let cls = "border-line dark:border-night-line hover:bg-paper-sink dark:hover:bg-night-soft";
            if (answered && isAnswer) cls = "border-emerald-400 bg-emerald-50 dark:bg-emerald-500/10";
            else if (answered && isPicked) cls = "border-brand-soft bg-brand-wash dark:bg-night-soft";
            else if (answered) cls = "border-line dark:border-night-line opacity-60";
            return (
              <button key={i} onClick={() => choose(i)} disabled={answered}
                      className={`w-full text-left rounded-xl border px-3 py-2 text-[14px] transition flex items-center gap-2 ${cls}`}>
                <span className="h-5 w-5 shrink-0 grid place-items-center rounded-full border border-current text-[11px] text-ink-faint dark:text-night-faint">
                  {String.fromCharCode(65 + i)}
                </span>
                <span className="flex-1"><InlineMd>{String(opt)}</InlineMd></span>
                {answered && isAnswer && <CheckIcon />}
                {answered && isPicked && !isAnswer && <XIcon />}
              </button>
            );
          })}
        </div>
        {answered && (
          <div className={`mt-3 text-[13.5px] rounded-xl px-3 py-2 md-explanation ${picked === answer_index
            ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            : "bg-brand-wash dark:bg-night-soft text-ink-soft dark:text-night-ink"}`}>
            <span className="font-medium">{picked === answer_index ? "Correct! " : "Not quite. "}</span>
            {explanation
              ? <InlineMd>{explanation}</InlineMd>
              : (picked === answer_index ? "Nice work." : `The answer is ${String.fromCharCode(65 + answer_index)}.`)}
          </div>
        )}
      </div>
    </div>
  );
}

const CheckIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>);
const XIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>);
