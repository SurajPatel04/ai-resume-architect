"use client";

import { useState } from "react";
import { FileText, Eye, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ResumeSnapshot } from "@/hooks/useChat";
import type {
    Resume,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
    ResumeSkillCategory,
} from "@/types/resume";

interface ResumePanelProps {
    snapshot: ResumeSnapshot;
    /** Small screens only: the same panel, slid over the chat. Ignored from lg up, where
     *  it is always in the layout. */
    open?: boolean;
    onClose?: () => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <section className="mb-5">
            <h4 className="mb-2 text-[10px] font-bold uppercase tracking-widest text-neutral-500">
                {title}
            </h4>
            {children}
        </section>
    );
}

/** One resume bullet, lit up while the chat is asking about that exact line. */
function Bullet({ focused, children }: { focused: boolean; children: React.ReactNode }) {
    return (
        <li
            className={cn(
                focused &&
                "rounded bg-amber-500/10 px-1 font-medium text-amber-200 marker:text-amber-500"
            )}
        >
            {children}
            {focused && (
                <span className="ml-1 text-amber-500/80">← this one</span>
            )}
        </li>
    );
}

function AtsCard({ score, feedback }: { score: number; feedback?: ResumeSnapshot["atsFeedback"] }) {
    // Red below 50, amber to 75, green above — matches how the score reads to a user.
    const tone =
        score >= 75 ? "text-green-400" : score >= 50 ? "text-amber-400" : "text-red-400";
    const bar =
        score >= 75 ? "bg-green-500" : score >= 50 ? "bg-amber-500" : "bg-red-500";

    return (
        <div className="mb-5 rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
            <div className="mb-2 flex items-baseline justify-between">
                <span className="text-[10px] font-bold uppercase tracking-widest text-neutral-500">
                    ATS match
                </span>
                <span className={cn("text-2xl font-bold tabular-nums", tone)}>{score}</span>
            </div>

            <div className="mb-3 h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
                <div className={cn("h-full rounded-full transition-all", bar)} style={{ width: `${score}%` }} />
            </div>

            {!!feedback?.missing_keywords?.length && (
                <div className="mb-2">
                    <p className="mb-1.5 text-[10px] uppercase tracking-wider text-neutral-500">Missing</p>
                    <div className="flex flex-wrap gap-1">
                        {feedback.missing_keywords.slice(0, 8).map((kw) => (
                            <span key={kw} className="rounded-md bg-red-500/10 px-2 py-0.5 text-xs text-red-300">
                                {kw}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {!!feedback?.matched_keywords?.length && (
                <div className="mb-2">
                    <p className="mb-1.5 text-[10px] uppercase tracking-wider text-neutral-500">Matched</p>
                    <div className="flex flex-wrap gap-1">
                        {feedback.matched_keywords.slice(0, 8).map((kw) => (
                            <span key={kw} className="rounded-md bg-green-500/10 px-2 py-0.5 text-xs text-green-300">
                                {kw}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {feedback?.feedback && (
                <p className="text-xs leading-relaxed text-neutral-400">{feedback.feedback}</p>
            )}
        </div>
    );
}

function QualityCard({ score, factors }: {
    score: number;
    factors?: ResumeSnapshot["qualityFeedback"];
}) {
    const percent = Math.round((score / 24) * 100);
    const tone = score >= 18 ? "text-green-400" : score >= 12 ? "text-amber-400" : "text-red-400";
    const bar = score >= 18 ? "bg-green-500" : score >= 12 ? "bg-amber-500" : "bg-red-500";

    return (
        <div className="mb-5 rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
            <div className="mb-2 flex items-baseline justify-between">
                <span className="text-[10px] font-bold uppercase tracking-widest text-neutral-500">
                    Resume quality
                </span>
                <span className={cn("text-2xl font-bold tabular-nums", tone)}>{score}/24</span>
            </div>
            <div className="mb-3 h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
                <div className={cn("h-full rounded-full transition-all", bar)} style={{ width: `${percent}%` }} />
            </div>
            {!!factors?.length && (
                <div className="space-y-1.5">
                    {factors.map((factor) => (
                        <div key={factor.name} className="flex items-center justify-between gap-3 text-xs">
                            <span className="text-neutral-400">{factor.name}</span>
                            <span className="font-medium tabular-nums text-neutral-200">{factor.score}/{factor.max_score}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

/**
 * The entry the chat is currently asking about: "experience[0]" -> section and index.
 * An unindexed path ("basics") focuses the section itself, which is why the index falls
 * back to -1 rather than 0 — nothing should light up entry zero by accident.
 */
function parseFocus(field?: string): { section: string; index: number } | null {
    if (!field) return null;
    const match = /^([a-z_]+)(?:\[(\d+)\])?$/i.exec(field);
    if (!match) return null;
    return { section: match[1], index: match[2] === undefined ? -1 : Number(match[2]) };
}

/** Marks the one entry under discussion. Amber, matching the "needs work" tone of the
 *  scores above it, and a left rule rather than a fill so the text stays readable. */
const FOCUS_ENTRY = "-ml-2 rounded-r border-l-2 border-amber-500/70 bg-amber-500/5 pl-2";

function LiveResume({ profile, focus }: { profile: Resume; focus?: ResumeSnapshot["focus"] }) {
    const target = parseFocus(focus?.field);
    const bullet = focus?.bulletIndex ?? null;
    const focused = (section: string, i: number) =>
        !!target && target.section === section && (target.index === i || target.index === -1);
    const basics = profile.basics || {};
    const contact = [basics.location, basics.phone, basics.email].filter(Boolean).join(" · ");
    const experience = profile.experience || [];
    const education = profile.education || [];
    const projects = profile.projects || [];
    const skills = profile.skills || [];
    const summary = profile.summary?.content;

    const isEmpty =
        !basics.name && !summary && !experience.length && !education.length &&
        !projects.length && !skills.length;

    if (isEmpty) {
        return (
            <p className="px-1 py-8 text-center text-xs text-neutral-600">
                Your resume will fill in here as you answer.
            </p>
        );
    }

    return (
        <div className="text-sm">
            {(basics.name || contact) && (
                <div className="mb-5 border-b border-neutral-800 pb-4">
                    {basics.name && <p className="text-base font-bold text-white">{basics.name}</p>}
                    {contact && <p className="mt-1 text-xs text-neutral-500">{contact}</p>}
                </div>
            )}

            {summary && (
                <Section title="Summary">
                    <p className="text-xs leading-relaxed text-neutral-300">{summary}</p>
                </Section>
            )}

            {experience.length > 0 && (
                <Section title="Experience">
                    {experience.map((exp: ResumeExperience, i: number) => (
                        <div key={i} className={cn("mb-3", focused("experience", i) && FOCUS_ENTRY)}>
                            <p className="text-xs font-semibold text-neutral-200">
                                {exp.position || "Role"}
                                {exp.company ? ` · ${exp.company}` : ""}
                            </p>
                            {(exp.start_date || exp.end_date) && (
                                <p className="text-[11px] text-neutral-600">
                                    {exp.start_date} {exp.end_date ? `– ${exp.end_date}` : ""}
                                </p>
                            )}
                            <ul className="mt-1 list-disc pl-4 text-[11px] leading-relaxed text-neutral-400 marker:text-neutral-700">
                                {(exp.highlights || []).map((hl: string, j: number) => (
                                    <Bullet key={j} focused={focused("experience", i) && bullet === j}>{hl}</Bullet>
                                ))}
                            </ul>
                        </div>
                    ))}
                </Section>
            )}

            {projects.length > 0 && (
                <Section title="Projects">
                    {projects.map((proj: ResumeProject, i: number) => (
                        <div key={i} className={cn("mb-3", focused("projects", i) && FOCUS_ENTRY)}>
                            <p className="text-xs font-semibold text-neutral-200">{proj.name || "Project"}</p>
                            <ul className="mt-1 list-disc pl-4 text-[11px] leading-relaxed text-neutral-400 marker:text-neutral-700">
                                {(proj.highlights || []).map((hl: string, j: number) => (
                                    <Bullet key={j} focused={focused("projects", i) && bullet === j}>{hl}</Bullet>
                                ))}
                            </ul>
                        </div>
                    ))}
                </Section>
            )}

            {education.length > 0 && (
                <Section title="Education">
                    {education.map((edu: ResumeEducation, i: number) => (
                        <div key={i} className={cn("mb-2", focused("education", i) && FOCUS_ENTRY)}>
                            <p className="text-xs font-semibold text-neutral-200">{edu.institution}</p>
                            <p className="text-[11px] text-neutral-500">
                                {[edu.study_type, edu.area].filter(Boolean).join(", ")}
                            </p>
                            {/* The interview collects these; nothing here ever showed them, so an answer
                  that included the years looked like it had been thrown away. */}
                            {(edu.start_date || edu.end_date) && (
                                <p className="text-[11px] text-neutral-600">
                                    {[edu.start_date, edu.end_date].filter(Boolean).join(" – ")}
                                </p>
                            )}
                        </div>
                    ))}
                </Section>
            )}

            {skills.length > 0 && (
                <Section title="Skills">
                    {skills.map((cat: ResumeSkillCategory, i: number) => (
                        <div key={i} className={cn("mb-2", focused("skills", i) && FOCUS_ENTRY)}>
                            {cat.name && <p className="text-[11px] font-medium text-neutral-400">{cat.name}</p>}
                            <div className="mt-1 flex flex-wrap gap-1">
                                {(cat.keywords || []).map((kw: string) => (
                                    <span key={kw} className="rounded-md bg-neutral-800 px-2 py-0.5 text-[11px] text-neutral-300">
                                        {kw}
                                    </span>
                                ))}
                            </div>
                        </div>
                    ))}
                </Section>
            )}
        </div>
    );
}

export function ResumePanel({ snapshot, open, onClose }: ResumePanelProps) {
    const { profile, pdfPath, atsScore, atsFeedback, qualityScore, qualityFeedback, focus } = snapshot;
    // null means "no explicit choice yet", which lets the finished PDF take over the
    // panel the moment it exists — but stops overriding the user once they pick a tab.
    const [tab, setTab] = useState<"live" | "pdf" | null>(null);
    const view = (tab ?? (pdfPath ? "pdf" : "live")) === "pdf" && pdfPath ? "pdf" : "live";

    return (
        <>
            {open && (
                <div className="fixed inset-0 z-40 bg-black/70 lg:hidden" onClick={onClose} aria-hidden />
            )}
            <aside
                className={cn(
                    "w-96 max-w-[85vw] shrink-0 flex-col border-l border-neutral-800 bg-neutral-950",
                    "hidden lg:flex",
                    open && "fixed inset-y-0 right-0 z-50 flex"
                )}
            >
                <div className="flex shrink-0 items-center gap-1 border-b border-neutral-800 px-3 py-2">
                    <button
                        onClick={() => setTab("live")}
                        className={cn(
                            "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                            view === "live" ? "bg-neutral-800 text-white" : "text-neutral-500 hover:text-neutral-300"
                        )}
                    >
                        <Eye size={13} />
                        Live
                    </button>
                    <button
                        onClick={() => setTab("pdf")}
                        disabled={!pdfPath}
                        title={pdfPath ? "Preview the generated PDF" : "Available once your resume is generated"}
                        className={cn(
                            "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-30",
                            view === "pdf" ? "bg-neutral-800 text-white" : "text-neutral-500 hover:text-neutral-300"
                        )}
                    >
                        <FileText size={13} />
                        PDF
                    </button>

                    {pdfPath && (
                        <a
                            href={pdfPath}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ml-auto text-xs text-neutral-500 underline-offset-2 hover:text-white hover:underline"
                        >
                            Download
                        </a>
                    )}

                    <button
                        onClick={onClose}
                        aria-label="Close the resume preview"
                        className={cn(
                            "flex h-8 w-8 items-center justify-center rounded-lg text-neutral-500 hover:bg-neutral-800 hover:text-white lg:hidden",
                            !pdfPath && "ml-auto"
                        )}
                    >
                        <X size={16} />
                    </button>
                </div>

                {view === "pdf" && pdfPath ? (
                    <iframe src={pdfPath} title="Generated resume" className="flex-1 bg-neutral-900" />
                ) : (
                    <div className="flex-1 overflow-y-auto p-4">
                        {typeof qualityScore === "number" && <QualityCard score={qualityScore} factors={qualityFeedback} />}
                        {typeof atsScore === "number" && <AtsCard score={atsScore} feedback={atsFeedback} />}
                        <LiveResume profile={profile || {}} focus={focus} />
                    </div>
                )}
            </aside>
        </>
    );
}