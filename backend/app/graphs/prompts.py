"""LLM prompt templates.

Every prompt the graph sends lives here. Templates use ``str.format`` placeholders;
literal braces intended for the model are doubled.
"""

# --- planner -----------------------------------------------------------------

INTENT = """
The user is interacting with an AI Resume Architect.
Current Workflow: {workflow}
User's latest message: "{answer}"

Determine whether the user wants to build their master profile (providing personal
details, answering questions about experience), tailor their existing resume for a
specific job/role, or edit something already in their resume.
If they are answering a question previously asked by the AI, it is BUILD_PROFILE.
If they are asking to change or correct a detail that is already recorded, it is EDIT_PROFILE.

If their intent is to tailor the resume (TAILOR_RESUME) and their message contains the job
description text, set `has_jd` to true. If they want to tailor it but did not provide the
job description, set `has_jd` to false.

If the message hands over a whole new entry to put on the resume — a named project with
its bullet points, another job, a degree, a certification — that is ADD_CONTENT, whatever
question was on screen at the time. Set `add_section` to the section it belongs in.
Someone pasting a project and writing "add this project" is ADD_CONTENT, not EDIT_PROFILE:
they are giving you something new, not correcting something already recorded.

If the message is about how the finished PDF LOOKS, or asks for it to be produced again,
that is RESTYLE. All of these are RESTYLE:

- "use my original layout", "match my uploaded design", "keep my format"
- "use the site layout", "your template is fine", "generate it in the site layout"
- "now generate the resume", "rebuild the PDF", "make it again"
- "change the layout", "different design"

RESTYLE is never EDIT_PROFILE, because no fact on the resume is changing — only which
template it is printed in, or the fact that it needs printing again. A message naming a
layout is answering which one to use, not asking a question, so never treat it as
unclear.
"""

# --- conversation_planner ----------------------------------------------------

MAY_FOLLOW_UP = """
1. Look at the MOST RECENT answer. Set `follow_up` ONLY if one of these is true:
     a. It answered part of what was asked and the rest still matters.
     b. It contradicts something recorded above — two different end dates for one job,
        a title that does not fit the dates, the same employer listed twice.
     c. Something was recorded that the extractor was unsure of, and getting it wrong
        would be embarrassing on a resume. Confirm it inside a natural question.
     d. It named something substantial — a product, a system, a team they ran — and
        said almost nothing about it. One more question about the scale, the stack,
        or what changed as a result is worth more than any question in the list below.
   An answer marked "rated thin" or "rated unusable" above is the strongest signal
   there is: the phrase after the rating says exactly what is missing, so ask about
   that and nothing else. An answer with no rating line was good enough — do not go
   back to it unless it contradicts something (b).
   Anything the waiting list below already covers is NOT a follow-up: that question is
   already scheduled, and asking it twice is how an interview turns into an
   interrogation. Match depth to substance — a thin answer about a phone number is
   just a phone number. If none of a/b/c/d applies, leave `follow_up` null; on most
   turns it is null.
"""

NO_FOLLOW_UP = """
1. Leave `follow_up` null this turn. You have already acted on every exchange above,
   so there is no new answer to judge.
"""

TURN_PLAN = """
You are running a resume interview, one question at a time. Decide what to ask next.

WHAT THE RESUME HOLDS SO FAR ({completion}% of its fields are filled):
{resume}

THE INTERVIEW SO FAR:
{transcript}

QUESTIONS WAITING TO BE ASKED — any one of these can be next:
{waiting}

Already given up on: {skipped}

Judge, in this order:
{follow_up_rule}
2. Is anything in the waiting list not worth asking any more? If what is already
   recorded tells a hiring manager who this person is and what they have done, name
   every remaining optional section in `drop_sections` and end the interview there.
   A finished resume now beats a marginally fuller one five questions later. Sections
   holding a required gap are not yours to drop; naming them does nothing.
3. Of what is left IN THE SECTION ALREADY ON THE TABLE, which single question buys
   the most? Weigh what an answer would come back with, not how many boxes it ticks:
   "what did you build, and what changed because of it" yields the technologies, the
   scale and the outcome at once, while a profile URL yields one string. Evidence
   beats completeness. Do not name a field from another section — finish this one
   first; the waiting list is already in the order the sections should be covered.

Rules:
- A follow-up must name a path that appears above and real field names of that item.
  A question whose answer has nowhere to be stored is worse than no question.
- Never re-open anything in the given-up list. Silence is the cheaper mistake: a
  question they did not need costs them more than a marginally thinner bullet gains.
- `next_field` must be copied from the waiting list above, or left empty.
"""

# --- generate_question -------------------------------------------------------

SKILL_CHIPS_EVIDENCE = """
THEY HAVE ALREADY DESCRIBED DOING THIS:
{evidence}

Every technology named above goes in the list FIRST, in the order it matters to the
role — they have demonstrably used it and being asked to type it again reads as not
having listened. Fill the remaining slots with what {role} postings commonly ask for.
"""

SKILL_CHIPS_COLD = """
List the skills that postings for this role name most often — the ones a recruiter
scans for.
"""

SKILL_CHIPS = """
A candidate is building a resume and is targeting this role: {role}
{evidence}
Concrete tools, languages and frameworks only. No soft skills.

These are shown as chips to tap, so each one must be the short name it would appear
as on a resume ("PostgreSQL", not "PostgreSQL database administration").
"""

QUESTION_ERROR_CONTEXT = """
CRITICAL: The user's previous answer for this field failed validation! Error: {error}
You MUST apologize and politely re-ask the user to provide the information in the correct format.
"""

QUESTION_INSTRUCTIONS = """
The user's resume is missing specific fields for the item {field}.
Specifically, these fields are missing and need to be filled: {missing}.
Reason: {reason}

Ask a short, conversational question to gather ONLY these missing fields: {missing}.
Do NOT ask for fields that are already filled. Combine the request for these missing
fields into one smooth question.

If the requested fields have clear, common answers (like 3-5 common skills for their
role), set ui to 'chips' and provide those as options. Otherwise, if it requires a
free-text response, set ui to 'text' and leave options empty.
"""

GENERATE_QUESTION = """
You are an expert resume assistant.
{error_context}

{known_context}

{instructions}

Never re-ask for anything listed as already recorded above, and word the question so it
fits what you already know about them.
Keep the question polite and under 2 sentences.
"""

# --- extract_entities --------------------------------------------------------

EXTRACT_TYPED = """
The user is filling in the {section} section of their resume.

Question asked: {question}
What it was about: {about}
Their answer: {answer}

Most recent interview turns (use only to avoid repeating an already answered or
skipped field):
{recent}

Fill in `items` with the actual {section} models. One item per {section} entry
described, in the order the user gave them.

For skills, each item is a named category. Preserve explicit headings exactly, such
as `Languages: JavaScript, TypeScript` or `Tools & DevOps: Docker, Git`; put the
heading in `name` and every listed skill in `keywords`. Do not collapse categories.

- The question is about ONE entry, but people answer with two jobs or two degrees in
  a single message. Anything you leave out is lost — nothing later asks for it again.
- Take everything they gave, not only what was asked for. Dates, a location, a link
  mentioned in passing all have a field here and all belong in it.
- Leave a field at its default when they did not give it. Never guess it, never carry
  a value from one entry to another, and never fill one from what you happen to know
  about the company or university they named.
- Bullet points belong to the entry they were written under, one per line. Never
  create generic responsibilities from only a company name or job title: `highlights`
  must contain only work details the user actually wrote or spoke.

Set is_skip if they declined or said they have none, and put nothing in `items`.

Then rate `sufficiency`. Ask yourself whether a hiring manager reading this on a
finished resume would see something real. "abc" or "asdf" as an institution is not a
university, it is a placeholder — that is 'unusable', however cleanly it parsed.
Being brief is not the same as being empty: "Acme" is a complete company name.
"""

EXTRACT_FLAT = """
The user was asked a question while filling in their resume.

Question asked: {question}
Their answer: {answer}

{instruction}

Set is_skip if they declined or said they have none, and leave the value empty.

Then rate `sufficiency`. Ask yourself whether a hiring manager reading this on a
finished resume would see something real. "abc" or "asdf" is not an answer, it is a
placeholder — that is 'unusable', however cleanly it parsed. Being brief is not the
same as being empty: "Python, Go" is a complete skills answer.
"""

EXTRACT_FREEFORM = """
The user was asked to provide information for their resume.
Section: {section}
Target Item: {field}
Requested Fields: {missing}
Question Asked: {question}
User's Answer: {answer}

Determine if the user provided the information or if they explicitly skipped/declined.
If they provided information, extract each provided field into the `entities` list with
a confidence score.
CRITICAL INSTRUCTION: Only include entities that the user ACTUALLY answered. If the user
provided 2 out of 3 requested fields, the 3rd field MUST be omitted entirely.
Use only the field names listed above: a name that is not one of them is dropped
silently and the user's answer is lost.

Then rate `sufficiency`. Ask yourself whether a hiring manager reading this value on a
finished resume would see something real. "abc" or "asdf" as an institution is not a
university, it is a placeholder — that is 'unusable', however cleanly it parsed.
Being brief is not the same as being empty: "Acme" is a complete company name.
"""

METRIC_INSTRUCTION = (
    "Pull out the figure or outcome they gave for that bullet. Take the number "
    "as they said it — never round it, scale it, or supply one they did not give."
)

# --- review_quality ----------------------------------------------------------

WEAK_BULLETS = """
These are the bullet points on someone's resume.

{listing}

Pick at most {budget} that would gain the most from one follow-up question, weakest
first. A bullet is weak when it describes a duty rather than an achievement, is vague
about what was actually built or changed, or claims an outcome with no result attached.
A number alone does not make a bullet strong — "worked on 2 teams" is still a duty.

For each one, write in `rewrite` how that bullet would read with its missing figure
in it, putting {{}} exactly where the number goes and its unit straight after. Draw
the measurement from what the bullet says the work actually did — a payment
integration moves failed transactions and settlement time, a caching layer moves
latency and hit rate. Keep every fact the original states and keep its stack: this
is the same bullet with one measurement added, not a replacement for it, and the
user is going to read it back against the line they wrote.

NEVER write a digit of your own, not a plausible one and not an example. The {{}} is
the only place a number enters this sentence; one you supplied is one the candidate
will be asked to defend in an interview and cannot.

Return the paths and indexes exactly as listed above. If every bullet is already
specific and carries a real result, return nothing — a needless question costs the
user more than a marginal bullet gains.
"""

# --- enhance_resume ----------------------------------------------------------

ENHANCE = """
You are an expert resume writer. The user has provided their resume information.
Your task is to heavily polish the professional summary, and the highlights/bullet
points of their experience and projects.

Guidelines:
1. Rewrite highlights to use strong action verbs.
2. Lead with the result WHEN THE BULLET ALREADY STATES ONE. Asking for a Result on
   every bullet is what makes a writer invent outcomes — a bullet with no stated
   outcome gets better wording and nothing else. No trailing "improving X",
   "enhancing Y", "optimizing Z" unless the input says so.
3. Make the summary highly impactful and concise (3-4 sentences max).
4. Fix any grammatical errors.
5. Every number, percentage, timespan and claim in your output must trace to the input.
   Invent nothing. This is someone's real resume and they will be asked about it.
6. Return AT MOST {max_bullets} highlights per entry, strongest first. People paste
   whole sections out of an old resume, and the job here is to turn that into the
   handful of lines worth reading — merge overlapping bullets, fold a weak one into
   the strong one next to it, and drop filler outright. Never split one bullet into
   several, and never return more than you were given.
7. Rewrite. A bullet returned word for word as it came in has not been enhanced.
8. Regroup the skills under headings that describe them — Languages, Frontend,
   Backend, Databases, Cloud & DevOps, AI & Data, Tools, or whatever actually fits
   what is there. Every skill in, every skill out: change the grouping, never the set.

Here is the current raw resume data:
{resume}

Output the enhanced fields in the exact same order as the raw data arrays.
"""

# --- score_ats ---------------------------------------------------------------

ATS_SCORE = """
You are an ATS (Applicant Tracking System) evaluator.

JOB DESCRIPTION:
---
{job_description}
---

CANDIDATE RESUME DATA:
---
{resume}
---

Score how well this resume matches the job description from 0 to 100, based on:
- Presence of the key skills, tools, and qualifications the JD asks for.
- Relevance of the experience and summary to the role.
- Keyword alignment.

List the important JD keywords that ARE present (matched_keywords) and those that are
MISSING (missing_keywords). Give 2-3 sentences of concrete, actionable feedback. Do NOT
invent skills the candidate has; base everything only on the resume data provided.
"""

# --- tailor_resume -----------------------------------------------------------

TAILOR = """
You are an expert resume writer tailoring a candidate's resume to a specific job.

TARGET JOB DESCRIPTION:
---
{job_description}
---

CANDIDATE'S CURRENT RESUME DATA:
---
{resume}
---

Your task:
1. Rewrite the professional summary to position the candidate for THIS job (3-4
   sentences max).
2. Rewrite and reorder the highlights of each experience and project to emphasize what
   matters most for this job. Lead with the most relevant, impactful bullets.
3. Reorder the candidate's EXISTING skills so the most job-relevant ones come first.

STRICT RULES:
- Do NOT invent experience, metrics, skills, or achievements the candidate did not mention.
- Only rephrase, reorder, and re-emphasize what is already there.
- Keep experience and project arrays in the EXACT same order as provided (only the
  highlights inside them change).
- Mirror the job description's terminology where it truthfully matches the candidate's
  real experience.
"""

# --- apply_edit --------------------------------------------------------------

EDIT_PLAN = """
The user wants to change something in their resume.

CURRENT VALUES:
{current_values}

THEIR REQUEST: "{instruction}"

Work out which fields they want changed and what the new values are.
Give one edit per entry you are changing: its section, the [n] shown above for it,
and the new values. Fill in ONLY the fields they asked to change and leave the rest
of that entry empty — anything you fill in overwrites what is on their resume.
Never invent a value.
If the request is vague or names something not listed above, set understood to
false and ask them what they meant.
"""

# --- confirm_import ----------------------------------------------------------

IMPORT_REVIEW = """
A resume was parsed from the user's uploaded document. We showed them a summary and
asked whether it looked right.

PARSED PROFILE:
{resume}

OUR QUESTION: {question}
THEIR REPLY: "{answer}"

Decide whether they confirmed it, and list ONLY the specific fields they asked to
change. If they said something is wrong but didn't say what, return confirmed=false
with no corrections. Never invent a correction they did not state.
"""

# --- parse_document ----------------------------------------------------------

PARSE_DOCUMENT = """
You are an expert resume parser. Extract structured information from the following raw
resume text. Ensure accuracy and organize contact information, work experience,
education, skills, and projects carefully.

Raw Resume Text:
---
{text}
---
"""

# --- process_verification ----------------------------------------------------

VERIFICATION = """
The user was asked to verify the extracted value '{value}' for the field '{field}'.
User's answer: "{answer}"

Did the user confirm the value is correct? If they provided a correction, extract it.
"""

# --- skill_gap ---------------------------------------------------------------

CLAIMED_SKILLS = """
We asked the candidate which of these skills, taken from a job description, they
actually have:

{offered}

THEIR REPLY: "{answer}"

Return only the ones they clearly said they have. If they were vague, said no, or
talked about something else, return nothing — claiming a skill someone does not have
is worse for them than leaving it off.

File each under one of their existing skill categories: {categories}
"""

# --- add_extras --------------------------------------------------------------

CERTIFICATION_ISSUERS = """
Suggest up to five likely issuing organizations for these certification names: {names}.
They are selectable suggestions only, not facts about the candidate. Use official issuer
names, not training providers, and return no generic companies unrelated to the credential.
"""

EXTRA_SKILLS = """
Suggest up to 8 concrete technical skills relevant to {context}.
Already listed skills: {existing}

Return only short languages, frameworks, tools, cloud services, or protocols that
are NOT already listed. These are suggestions only: never claim the candidate has
them, and do not include soft skills or sentences.
"""

DEGREE_SUGGESTIONS = """
A candidate is adding a qualification to their resume. They chose the level: {level}

ALREADY ON THEIR RESUME: {held}

List up to 8 qualifications at that level that this person plausibly holds or would go
on to, most likely first. Follow from what they already have: someone with a B.Sc is
choosing between an M.Sc, an MCA and an MBA; someone with an LLB is looking at an LLM;
an MBBS leads to an MD or an MS. With nothing recorded, list the most common ones.

Short names exactly as a resume writes them — "M.Tech", "LLM", "MBBS", not sentences or
programme descriptions. These are shown as buttons to tap, so no duplicates and nothing
they already have.
"""

PARSE_CERTIFICATIONS = """
The user was asked which certifications, licences or awards they hold.

THEIR REPLY: "{answer}"

Pull out one entry per credential they named. Leave issuer, date, and credential URL
empty when they did not say them — a resume that states details they never mentioned
is a fabrication and they will be asked about them. Return nothing if they named no
credential.
"""

PARSE_EDUCATION = """
The user was asked to give a qualification to add to their resume.

THEIR REPLY: "{answer}"

Pull out one entry per qualification they named. `study_type` is the degree ("MCA",
"B.Tech", "Bachelor of Science"), `area` the field of study, `institution` the school
or university. Leave dates and grade empty when they did not say them — a resume
stating a GPA they never gave is a fabrication. Return nothing if they named no
qualification.
"""

PARSE_CUSTOM_ENTRIES = """
The user was asked what to put under the "{section}" section of their resume.

THEIR REPLY: "{answer}"

Pull out one entry per thing they named. `title` is what it is called, `subtitle` who
it was with or for, `date` the period as they wrote it, `highlights` any bullet points
they gave. Leave a field empty when they did not say it — a resume stating a date or an
organisation they never mentioned is a fabrication. Return nothing if they named none.
"""

PARSE_EXTRA_SKILLS = """
The user was asked which extra skills to add to their resume.

THEIR REPLY: "{answer}"

Pull out one entry per skill they named, exactly as they wrote it. File each under one
of their existing categories: {categories}. Only name a new category when none of those
fit. Add nothing they did not say.
"""

# --- choose_style ------------------------------------------------------------

READ_LAYOUT = """
This is the first page of a resume. Describe HOW IT LOOKS, not what it says — none of
the person's details matter here, only the design decisions the page makes.

- font_family: is the body type serif (Times, Georgia, Garamond — letters with feet) or
  sans (Arial, Calibri, Helvetica — plain strokes)?
- name_align: is the name at the top centred, or set to the left margin?
- name_size_pt: roughly how big is the name, in points, if the body text is about 10pt?
- heading_case: are section headings in Title Case or ALL CAPS?
- heading_rule: is there a horizontal line under each section heading?
- accent_color: if headings or rules are in a colour other than black, give it as #rrggbb.
  Black or dark grey headings mean an empty string. Do not guess a brand colour.
- contact_icons: does the contact line at the top put a small icon in front of each
  item — a pin before the city, an envelope before the email, a GitHub mark before the
  link? True only if you can actually see icons there, not if the items are separated
  by bullets or pipes.
- bullet_marker: which character starts each bullet — one of • - – ‣ ▪ ◦
- section_order: the sections in the order they appear down the page, using only these
  names: {sections}. Skip any the page does not have. A "Profile", "Objective" or
  "About me" block is `summary`; "Technical Skills" or "Core Competencies" is `skills`;
  "Work History" or "Employment" is `experience`.

These were read straight out of the PDF's own instructions, so they are already right:

{measured}

Do not repeat those or argue with them — whatever you put in those fields is discarded.
They are here so you can see what is already known and spend your attention on the rest.
They also tell you what kind of document this is: if a sidebar was measured, the page has
two columns, and `section_order` should list the sections down the sidebar first and then
down the main panel.

Anything absent from that list was not measurable and is yours to answer. That is the
whole reason you are being asked: a scanned or flattened resume yields none of the above,
and then everything below comes from you.

Report what is on the page. If something is genuinely unclear, leave that field at its
default rather than inventing a value — a wrong answer here changes how someone's resume
looks and they may not notice which part came from a guess.
"""
