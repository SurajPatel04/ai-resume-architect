
#set document(title: "Suraj Patel")
#set page(margin: (x: 0.9in, y: 0.9in))
#set text(size: 11pt)

#show heading: it => [
  #set text(size: 11pt, weight: "regular")
  #block(smallcaps(it.body))
  #v(-0.2em)
  #line(length: 100%, stroke: 0.5pt)
  #v(0.1em)
]

#align(center)[
  #text(16pt, weight: "bold")[Suraj Patel]
  
  Lucknow, Uttar Pradesh, India | +91 9260923895 | surajpatel9390\@gmail.com
  
  linkedin.com/in/suraj-patel-9201b2381/ | github.com/SurajPatel04
]


= Summary
Dynamic Software Engineer specializing in agentic AI workflows and multimodal RAG platforms, with a proven track record in developing real-time backend systems. Expert in building production-level LLM applications utilizing Python, FastAPI, Node.js, and LangChain, with a strong focus on scalable REST APIs, Redis caching, and cloud deployment. Committed to delivering innovative solutions that enhance performance and user experience.

= Experience

*Careerboat* #h(1fr) Dec 2025 \- Present \
_Full Stack Engineer_, 
- Reduced LLM token consumption by 40% for the AI interview service by architecting stateful Node.js APIs with MongoDB checkpointing and dynamic context summarization across multi-turn sessions, significantly enhancing efficiency.
- Engineered a real-time streaming layer over Server-Sent Events and AWS S3, achieving a time-to-first-audio of approximately 2 seconds, which improved user engagement by delivering token-by-token responses.
- Revamped a high-volume job search API by redesigning MySQL FULLTEXT queries and ranking algorithms, slashing search latency from 1-5 minutes to just 5-10 seconds while enhancing search relevance.
- Integrated the Razorpay payment gateway for secure transactions, implementing custom backend logic for discount coupons, which streamlined the payment process.

= Education

*Amity University Online* #h(1fr) Jul 2024 \- Jun 2026 \
Master's in Master of Computer Applications (MCA)

*Lucknow Christian College* #h(1fr) Jul 2021 \- Jun 2024 \
Bachelor's in Bachelor of Science

= Projects

*InsightFlow – Multimodal RAG Platform* #h(1fr) insightflow.surajpatel.dev | github.com/SurajPatel04/ai-multimedia-rag-app
- Designed a two-phase ingestion flow that ensures uploads are confirmed before processing, effectively eliminating unnecessary embedding costs on unconfirmed files.
- Integrated Deepgram for timestamped transcription with clickable media citations, facilitating precise retrieval and playback of media content to the exact second.
- Implemented Redis semantic caching for repeated queries, alongside LangGraph-based conversation memory management, and deployed on GCP using Docker and GitHub Actions CI/CD.

*AI Manim Video Generator* #h(1fr) video.surajpatel.dev | github.com/SurajPatel04/manimVideoGenerate
- Engineered a self-healing generation loop with Vision QA, leveraging Vision LLMs (GPT-4o-mini/Gemini) to visually validate rendered frames against user intent, boosting execution success rates from approximately 60% to over 90%.
- Developed a scalable, asynchronous rendering architecture utilizing Celery, Redis, and Supabase to support concurrent generation, real-time polling, and in-flight task cancellation, secured through JWT and Google OAuth.

= Skills

- *Languages*: JavaScript, TypeScript, Python

- *Frontend*: React, Redux, HTML5, CSS3

- *Backend*: Node.js, Express.js, FastAPI, REST APIs, JWT, OAuth 2.0

- *Databases & Caching*: PostgreSQL (Prisma), SQL, MongoDB (Mongoose, Beanie), Redis, FAISS (Vector DB)

- *AI*: LangChain, LangGraph, LangSmith (LLM observability), OpenAI API, Gemini API, RAG, Prompt Engineering

- *Tools & DevOps*: AWS (S3), GCP, Docker, Git, GitHub Actions, Linux, Bash/Shell, Celery

- *Core Fundamentals*: Data Structures & Algorithms, Object-Oriented Programming (OOP), System Design
