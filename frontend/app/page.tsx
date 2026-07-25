import Link from "next/link";

export default function Home() {
  return (
    <div className="min-h-screen bg-black text-white selection:bg-white/20 overflow-x-hidden">
      {/* Nav */}
      <nav className="fixed top-0 z-50 w-full border-b border-white/5 bg-black/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-white flex items-center justify-center">
              <svg
                width="18"
                height="18"
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
            <span className="text-xl font-bold tracking-tight">
              AI Resume Architect
            </span>
          </div>
          <div className="flex items-center gap-4 sm:gap-6">
            <Link
              href="/signin"
              className="text-sm font-medium text-neutral-400 hover:text-white transition-colors"
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              className="rounded-full bg-white px-6 py-2.5 text-sm font-bold text-black hover:bg-neutral-200 transition-all active:scale-95 shadow-[0_0_20px_rgba(255,255,255,0.1)]"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <main className="relative pt-40 pb-20 bg-[radial-gradient(circle_at_50%_0%,rgba(255,255,255,0.03)_0%,transparent_50%)]">
        <div className="mx-auto max-w-7xl px-6 text-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-neutral-400 mb-10 backdrop-blur-md">
            AI-powered resume building
          </span>

          <h1 className="bg-gradient-to-br from-white via-white to-neutral-500 bg-clip-text text-4xl sm:text-6xl md:text-[90px] font-extrabold tracking-tighter text-transparent mb-10 leading-[1.1] md:leading-[0.95]">
            Build resumes that
            <br className="hidden sm:block" />
            <span className="text-neutral-400 font-serif italic">
              get you hired.
            </span>
          </h1>

          <p className="mx-auto max-w-2xl text-base md:text-xl text-neutral-400 leading-relaxed mb-14 font-medium px-4 md:px-0">
            The only platform that transforms your experience into
            professionally crafted, ATS-optimised resumes using advanced AI.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-6 px-6">
            <Link
              href="/signup"
              className="group relative flex w-full sm:w-auto items-center justify-center gap-3 rounded-full bg-white px-8 py-4 md:px-10 md:py-5 text-lg md:text-xl font-bold text-black shadow-[0_0_40px_rgba(255,255,255,0.1)] hover:bg-neutral-200 transition-all active:scale-95"
            >
              Start Building
              <svg
                className="h-5 w-5 md:h-6 md:w-6 transition-transform group-hover:translate-x-1.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            </Link>
          </div>

          {/* How it Works */}
          <div className="mt-48 py-20">
            <div className="text-center mb-20">
              <h2 className="text-3xl md:text-5xl font-bold mb-6">
                Simple, yet powerful workflow
              </h2>
              <p className="text-neutral-500 max-w-xl mx-auto">
                Three steps to transform your career story into a
                professional resume.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-12 relative">
              <div className="absolute top-1/2 left-0 w-full h-px bg-gradient-to-r from-transparent via-neutral-800 to-transparent -z-10 hidden md:block" />

              {[
                {
                  step: "01",
                  icon: (
                    <svg
                      className="h-8 w-8 text-white"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                      <circle cx="8.5" cy="7" r="4" />
                      <line x1="20" y1="8" x2="20" y2="14" />
                      <line x1="23" y1="11" x2="17" y2="11" />
                    </svg>
                  ),
                  title: "Sign Up",
                  desc: "Create your account in seconds with just your name, email, and password.",
                },
                {
                  step: "02",
                  icon: (
                    <svg
                      className="h-8 w-8 text-white"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                      <line x1="16" y1="13" x2="8" y2="13" />
                      <line x1="16" y1="17" x2="8" y2="17" />
                    </svg>
                  ),
                  title: "Add Your Details",
                  desc: "Input your experience, skills, and education. Our AI handles the rest.",
                },
                {
                  step: "03",
                  icon: (
                    <svg
                      className="h-8 w-8 text-white"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                    </svg>
                  ),
                  title: "Download & Apply",
                  desc: "Get a polished, ATS-optimised resume ready to land your dream job.",
                },
              ].map((item, i) => (
                <div key={i} className="flex flex-col items-center">
                  <div className="h-16 w-16 rounded-2xl bg-neutral-900 border border-neutral-800 flex items-center justify-center mb-8 shadow-2xl">
                    {item.icon}
                  </div>
                  <h3 className="text-2xl font-bold mb-4">{item.title}</h3>
                  <p className="text-neutral-500 text-center max-w-[250px]">
                    {item.desc}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-white/5 py-16 mt-20">
        <div className="mx-auto max-w-7xl px-6">
          <div className="flex flex-col md:flex-row items-center justify-center gap-6 md:gap-10 text-neutral-500 text-sm">
            <div className="flex items-center gap-3">
              <div className="h-6 w-6 rounded bg-white/10 flex items-center justify-center">
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="white"
                  strokeWidth="2"
                >
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
              </div>
              <p className="font-medium">
                © 2026 AI Resume Architect.
              </p>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
