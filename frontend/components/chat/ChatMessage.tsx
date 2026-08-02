"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import type { ChatMessage as ChatMessageType } from "@/hooks/useChat";

interface ChatMessageProps {
  message: ChatMessageType;
  isReceiving?: boolean;
  onSendMessage?: (content: string) => void;
}

/**
 * How the assistant's markdown renders.
 *
 * Spelled out here rather than with `prose`: the typography plugin is not installed, so
 * those classes were silently doing nothing and Preflight's zeroed margins ran every
 * paragraph, list and quote together. The blockquote matters most — the backend puts the
 * exact resume line being asked about inside one, and it has to look like a quotation of
 * the user's own resume rather than more of the question. Its amber rule is deliberately
 * the same as the panel's highlight, so the line in the chat and the line in the preview
 * read as the same thing.
 */
const MARKDOWN = {
  p: (props: React.ComponentProps<"p">) => <p className="mb-2 leading-relaxed last:mb-0" {...props} />,
  strong: (props: React.ComponentProps<"strong">) => (
    <strong className="font-semibold text-white" {...props} />
  ),
  em: (props: React.ComponentProps<"em">) => <em className="italic text-neutral-300" {...props} />,
  ul: (props: React.ComponentProps<"ul">) => (
    <ul className="mb-2 list-disc space-y-1 pl-5 marker:text-neutral-600 last:mb-0" {...props} />
  ),
  ol: (props: React.ComponentProps<"ol">) => (
    <ol className="mb-2 list-decimal space-y-1 pl-5 marker:text-neutral-600 last:mb-0" {...props} />
  ),
  blockquote: (props: React.ComponentProps<"blockquote">) => (
    <blockquote
      className="my-3 rounded-r-lg border-l-2 border-amber-500/70 bg-amber-500/5 py-2 pl-3 pr-2 text-[13px] italic leading-relaxed text-amber-100/90 [&>p]:mb-0"
      {...props}
    />
  ),
  a: (props: React.ComponentProps<"a">) => (
    <a
      className="font-medium text-white underline underline-offset-2 hover:text-neutral-300"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  code: (props: React.ComponentProps<"code">) => (
    <code className="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[12px] text-neutral-200" {...props} />
  ),
  h1: (props: React.ComponentProps<"h1">) => <h1 className="mb-2 text-base font-bold text-white" {...props} />,
  h2: (props: React.ComponentProps<"h2">) => <h2 className="mb-2 text-sm font-bold text-white" {...props} />,
  h3: (props: React.ComponentProps<"h3">) => <h3 className="mb-1 text-sm font-semibold text-white" {...props} />,
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2024-03" (what a month input gives) -> "Mar 2024" (what a resume says). */
function monthLabel(value: string): string {
  const [year, month] = value.split("-");
  return MONTHS[Number(month) - 1] ? `${MONTHS[Number(month) - 1]} ${year}` : "";
}

/**
 * Two month pickers and a "still here" toggle, for the one answer a phone keyboard is
 * worst at. Native `<input type="month">` rather than a date-picker dependency — it is
 * the platform's own picker, it is already localised, and it cannot produce a date the
 * user did not mean. The reply is sent as ordinary text, so the graph extracts it exactly
 * as it would a typed "Mar 2022 – Present".
 */
function DateRange({ onSend }: { onSend: (content: string) => void }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [present, setPresent] = useState(false);

  const ready = !!start && (present || !!end);
  const field =
    "rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2 text-sm text-white " +
    "[color-scheme:dark] focus:border-neutral-500 focus:outline-none disabled:opacity-40";

  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium uppercase tracking-wider text-neutral-500">From</span>
          <input type="month" value={start} onChange={(e) => setStart(e.target.value)} className={field} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium uppercase tracking-wider text-neutral-500">To</span>
          <input
            type="month"
            value={end}
            disabled={present}
            onChange={(e) => setEnd(e.target.value)}
            className={field}
          />
        </label>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setPresent((on) => !on)}
          aria-pressed={present}
          className={cn(
            "min-h-9 rounded-full border px-4 text-sm font-medium transition-colors",
            present
              ? "border-white bg-white text-black"
              : "border-neutral-700 bg-neutral-800 text-neutral-200 hover:bg-neutral-700"
          )}
        >
          {present ? "✓ I still work here" : "I still work here"}
        </button>
        <button
          onClick={() =>
            onSend(`${monthLabel(start)} – ${present ? "Present" : monthLabel(end)}`)
          }
          disabled={!ready}
          className="min-h-9 rounded-full bg-white px-4 text-sm font-semibold text-black transition-transform hover:scale-105 active:scale-95 disabled:opacity-30 disabled:hover:scale-100"
        >
          {ready ? `Send ${monthLabel(start)} – ${present ? "Present" : monthLabel(end)}` : "Pick the dates"}
        </button>
      </div>
    </div>
  );
}

/**
 * Tap several, send once — for the skill chips the backend derives from the target role.
 * Anything the list missed still gets typed in the box below; these are a shortcut, not
 * a closed set, and the backend reads the reply as an ordinary comma-separated answer.
 */
function MultiSelect({
  options,
  onSend,
}: {
  options: string[];
  onSend: (content: string) => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);

  const toggle = (opt: string) =>
    setPicked((prev) =>
      prev.includes(opt) ? prev.filter((o) => o !== opt) : [...prev, opt]
    );

  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const on = picked.includes(opt);
          return (
            <button
              key={opt}
              onClick={() => toggle(opt)}
              aria-pressed={on}
              className={cn(
                "px-4 py-1.5 rounded-full text-sm font-medium border transition-colors cursor-pointer",
                on
                  ? "bg-white text-black border-white"
                  : "bg-neutral-800 hover:bg-neutral-700 text-neutral-200 border-neutral-700"
              )}
            >
              {on ? `✓ ${opt}` : opt}
            </button>
          );
        })}
      </div>

      <button
        onClick={() => onSend(picked.join(", "))}
        disabled={picked.length === 0}
        className="mt-3 rounded-full bg-white px-4 py-1.5 text-sm font-semibold text-black transition-transform hover:scale-105 active:scale-95 disabled:opacity-30 disabled:hover:scale-100"
      >
        {picked.length ? `Add ${picked.length} selected` : "Select some, or type your own"}
      </button>
    </div>
  );
}

/**
 * The finished bullet, with the one number missing from it left as a box to type in.
 *
 * The backend sends the whole rewritten line with `{}` marking where the figure goes,
 * and the input is rendered in that spot rather than beside it. That is the point: the
 * user is approving a sentence, not answering a question about one, so they read it as
 * it will appear on the resume and the only word in it that is theirs is the one they
 * typed. What gets sent back is that same sentence, and `read_slot` on the backend
 * recognises it and stores it verbatim — no model re-derives it, so what was on screen
 * is what lands.
 *
 * The box starts empty and nothing ever prefills it. A plausible "30" that somebody
 * tabs past is a figure they never measured, printed on a real resume, and asked about
 * in an interview they then fail — the rest of the pipeline refuses to invent numbers,
 * and this refuses to invent them on the user's behalf.
 *
 * Free text, not `type="number"`: real answers include "2M", "1.5" and "40k", and a
 * spinner that rejects them is worse than no spinner.
 */
function MetricInput({
  template,
  onSend,
}: {
  template: string;
  onSend: (content: string) => void;
}) {
  const [value, setValue] = useState("");

  const slot = template.indexOf("{}");
  const before = template.slice(0, slot);
  const after = template.slice(slot + 2);

  const figure = value.trim();
  const sentence = `${before}${figure}${after}`;

  return (
    <div className="mt-4">
      <div className="rounded-lg border-l-2 border-amber-500/70 bg-amber-500/5 py-2.5 pl-3 pr-2 text-[13px] leading-loose text-amber-100/90">
        {before}
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && figure) onSend(sentence);
          }}
          inputMode="decimal"
          size={Math.max(figure.length, 3)}
          placeholder="___"
          aria-label="The figure you remember for this bullet point"
          className="mx-0.5 w-16 rounded border border-amber-500/40 bg-neutral-900 px-1.5 py-0.5 text-center text-[13px] font-semibold text-white placeholder:text-neutral-600 focus:border-amber-400 focus:outline-none"
        />
        {after}
      </div>

      <button
        onClick={() => onSend(sentence)}
        disabled={!figure}
        className="mt-3 min-h-9 rounded-full bg-white px-4 text-sm font-semibold text-black transition-transform hover:scale-105 active:scale-95 disabled:opacity-30 disabled:hover:scale-100"
      >
        {figure ? "Use this bullet" : "Type the figure you remember"}
      </button>
    </div>
  );
}

/**
 * One proposed bullet with its blank rendered as a box, for use inside a list.
 *
 * Value and setter are lifted to the parent: the gate sends every filled line in one
 * message, so the state has to live where the send button can see all of it.
 */
function SlotLine({
  template,
  value,
  onChange,
  onSubmit,
}: {
  template: string;
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
}) {
  const slot = template.indexOf("{}");
  const before = template.slice(0, slot);
  const after = template.slice(slot + 2);

  return (
    <div className="rounded-lg border-l-2 border-amber-500/70 bg-amber-500/5 py-2.5 pl-3 pr-2 text-[13px] leading-loose text-amber-100/90">
      {before}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSubmit();
        }}
        inputMode="decimal"
        placeholder="___"
        aria-label="The figure you remember for this bullet point"
        className="mx-0.5 w-16 rounded border border-amber-500/40 bg-neutral-900 px-1.5 py-0.5 text-center text-[13px] font-semibold text-white placeholder:text-neutral-600 focus:border-amber-400 focus:outline-none"
      />
      {after}
    </div>
  );
}

/**
 * Every weak bullet the review found, each with the figure it is missing left blank.
 *
 * The whole card is one turn: fill in the ones you remember, leave the rest empty, send
 * once. Three separate questions, each answerable with "I don't have that number", is
 * the shape this gate exists to avoid — and having read all three the user already
 * knows which they can answer, so making them wait to be asked one at a time spends
 * three turns to learn what they knew at the start.
 *
 * Only the filled lines are sent, one per line, each a complete sentence. The backend
 * matches each against the template it came from, so a user who fills in only the third
 * box has that figure land on the third bullet — position is never assumed.
 *
 * Blanks stay blank. Nothing here prefills a plausible figure, for the same reason
 * nothing else in this pipeline does: an untouched default is a number the candidate
 * never measured and will be asked to defend.
 */
function ImpactGate({
  gaps,
  onSend,
}: {
  gaps: { label: string; original: string; reason: string; template: string }[];
  onSend: (content: string) => void;
}) {
  const [values, setValues] = useState<Record<number, string>>({});

  const filled = gaps
    .map((gap, i) => ({ gap, figure: (values[i] || "").trim() }))
    .filter(({ gap, figure }) => gap.template && figure)
    .map(({ gap, figure }) => gap.template.replace("{}", figure));

  const send = () => {
    if (filled.length) onSend(filled.join("\n"));
  };

  return (
    <div className="mt-4 space-y-5">
      {gaps.map((gap, i) => (
        <div key={i} className="space-y-2">
          <p className="text-sm font-semibold text-white">{gap.label}</p>
          <blockquote className="rounded-r-lg border-l-2 border-neutral-700 bg-neutral-800/40 py-1.5 pl-3 pr-2 text-[13px] italic leading-relaxed text-neutral-400">
            {gap.original}
          </blockquote>
          <p className="text-[13px] text-neutral-400">
            Why it could be stronger: {gap.reason}.
          </p>
          {gap.template ? (
            <SlotLine
              template={gap.template}
              value={values[i] || ""}
              onChange={(next) => setValues((prev) => ({ ...prev, [i]: next }))}
              onSubmit={send}
            />
          ) : null}
        </div>
      ))}

      <button
        onClick={send}
        disabled={!filled.length}
        className="min-h-9 rounded-full bg-white px-4 text-sm font-semibold text-black transition-transform hover:scale-105 active:scale-95 disabled:opacity-30 disabled:hover:scale-100"
      >
        {filled.length
          ? `Add ${filled.length === 1 ? "this bullet" : `these ${filled.length} bullets`}`
          : "Fill in any you remember"}
      </button>
    </div>
  );
}

export function ChatMessage({ message, isReceiving, onSendMessage }: ChatMessageProps) {
  const isAi = message.role === "ai";

  return (
    <div
      className={cn(
        "flex w-full mb-6",
        isAi ? "justify-start" : "justify-end"
      )}
    >
      <div
        className={cn(
          // Wider on a phone than on a desktop: the assistant's bubble is what carries
          // the chips and the date pickers, and 85% of a narrow screen wraps them badly.
          "max-w-[92%] rounded-2xl px-4 py-3 sm:max-w-[85%] sm:px-5 sm:py-4",
          isAi
            ? "bg-neutral-900/50 border border-neutral-800 text-neutral-200 shadow-sm"
            : "bg-white text-black shadow-sm"
        )}
      >
        {isAi && (
          <div className="flex items-center gap-2 mb-2 pb-2 border-b border-neutral-800">
            <div className="h-5 w-5 rounded bg-white flex items-center justify-center shrink-0">
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="black"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </div>
            <span className="text-xs font-bold uppercase tracking-widest text-neutral-400">
              AI Resume Architect
            </span>
          </div>
        )}

        <div className="max-w-none break-words text-sm">
          {isAi ? (
            message.content ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN}>
                {message.content}
              </ReactMarkdown>
            ) : isReceiving ? (
              <div className="flex items-center gap-1.5 h-6">
                <span className="w-1.5 h-1.5 bg-neutral-500 rounded-full animate-bounce [animation-delay:-0.3s]"></span>
                <span className="w-1.5 h-1.5 bg-neutral-500 rounded-full animate-bounce [animation-delay:-0.15s]"></span>
                <span className="w-1.5 h-1.5 bg-neutral-500 rounded-full animate-bounce"></span>
              </div>
            ) : (
              <p className="opacity-50 italic">Empty response</p>
            )
          ) : (
            <p className="whitespace-pre-wrap font-medium">{message.content}</p>
          )}
        </div>

        {isAi && message.ui === "multi_select" && !!message.options?.length && (
          <MultiSelect
            options={message.options}
            onSend={(content) => onSendMessage && onSendMessage(content)}
          />
        )}

        {isAi && message.ui === "dates" && (
          <DateRange onSend={(content) => onSendMessage && onSendMessage(content)} />
        )}

        {isAi && message.ui === "metric" && message.meta?.template?.includes("{}") && (
          <MetricInput
            template={message.meta.template}
            onSend={(content) => onSendMessage && onSendMessage(content)}
          />
        )}

        {isAi && message.ui === "impact_gate" && !!message.meta?.gaps?.length && (
          <ImpactGate
            gaps={message.meta.gaps}
            onSend={(content) => onSendMessage && onSendMessage(content)}
          />
        )}

        {/* Every ui except the skills list can carry quick replies — a date question
            still needs its way out, and that arrives as an ordinary option. */}
        {isAi && message.ui !== "multi_select" && !!message.options?.length && (
          <div className="mt-4 flex flex-wrap gap-2">
            {message.options.map((opt, i) => (
              <button
                key={i}
                onClick={() => onSendMessage && onSendMessage(opt)}
                className="min-h-9 cursor-pointer rounded-full border border-neutral-700 bg-neutral-800 px-4 text-sm font-medium text-neutral-200 transition-colors hover:border-neutral-500 hover:bg-neutral-700 hover:text-white active:scale-95"
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}