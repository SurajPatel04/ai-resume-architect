/**
 * What the graph is doing right now.
 *
 * The backend already names the node it just finished on every `graph_update`, so this
 * costs nothing extra on the wire — and a run that goes enhance → render → score takes
 * long enough that a bare spinner reads as a hang.
 */
const NODE_LABELS: Record<string, string> = {
    planner: "Working out what you need",
    parse_document: "Reading your resume",
    confirm_import: "Checking what I read",
    extract_entities: "Taking that down",
    verify_entities: "Double-checking that",
    process_verification: "Taking that down",
    validate_entities: "Checking that fits",
    merge_profile: "Saving your answer",
    analyze_gaps: "Looking for what's missing",
    review_quality: "Reading your bullet points",
    conversation_planner: "Picking the next question",
    generate_question: "Writing the next question",
    apply_edit: "Making that change",
    tailor_resume: "Tailoring to the job",
    score_ats: "Scoring against the job",
    score_resume_quality: "Checking resume quality",
    enhance_resume: "Polishing the wording",
    render_resume: "Building your PDF",
};

export function ThinkingIndicator({ node }: { node?: string | null }) {
    const label = (node && NODE_LABELS[node]) || "Thinking";

    return (
        <div className="mb-6 flex w-full justify-start">
            <div
                className="flex items-center gap-3 rounded-2xl border border-neutral-800 bg-neutral-900/50 px-5 py-3"
                role="status"
                aria-live="polite"
            >
                <div className="flex items-center gap-1.5">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-neutral-500 [animation-delay:-0.3s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-neutral-500 [animation-delay:-0.15s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-neutral-500" />
                </div>
                <span className="text-sm text-neutral-400">{label}…</span>
            </div>
        </div>
    );
}