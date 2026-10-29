import Link from "next/link";
import {
  ArrowRight,
  Boxes,
  Check,
  GitBranch,
  Layers,
  ShieldCheck,
  Sparkles,
  Terminal,
  Users,
  Zap,
} from "lucide-react";

const PIPELINE = [
  { step: "01", title: "Detect", text: "The employee notices a capability it does not have." },
  { step: "02", title: "Generate", text: "The engine writes an implementation and its test suite." },
  { step: "03", title: "Prove", text: "Static analysis plus sandboxed tests — no test pass, no register." },
  { step: "04", title: "Reuse", text: "The capability becomes a versioned tool for every future task." },
];

const FEATURES = [
  {
    icon: Terminal,
    title: "Real execution engine",
    text: "Queued, planned, running, awaiting approval, recovering — a real lifecycle with bounded loops, timeouts and cancellation, not a chat window.",
  },
  {
    icon: Layers,
    title: "21 built-in tools",
    text: "Files, web search and fetch, sandboxed commands, data profiling, archives, artifacts, delegation and memory — all with validated schemas.",
  },
  {
    icon: ShieldCheck,
    title: "Sandboxed by default",
    text: "Generated code runs in a separate process with CPU, memory and time limits, an allow-listed command policy and a private network namespace.",
  },
  {
    icon: Users,
    title: "Teams, not swarms",
    text: "Delegate to a named employee with a bounded depth; children run with the intersection of permissions, so delegation can never widen access.",
  },
  {
    icon: Zap,
    title: "Free models first",
    text: "Talk to Ollama out of the box, or any OpenAI-compatible endpoint. No paid API key is required to run your own workforce.",
  },
  {
    icon: GitBranch,
    title: "Everything observable",
    text: "Every state change, tool call, approval and error is persisted as an event and streamed live. Failures are reported honestly.",
  },
];

const STATS = [
  { value: "9", label: "employee templates" },
  { value: "21", label: "builtin tools" },
  { value: "8", label: "task states" },
  { value: "MIT", label: "open source" },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      {/* ------------------------------------------------------------ nav */}
      <header className="sticky top-0 z-30 border-b border-line bg-canvas/85 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-graphite text-sm font-bold text-white">
              B
            </span>
            <span className="text-[17px] font-semibold tracking-tight">Bozii</span>
            <span className="ml-1 hidden rounded-full border border-line bg-surface px-2 py-0.5 text-[10px] font-medium text-muted sm:inline">
              open source
            </span>
          </div>
          <nav className="hidden items-center gap-7 text-sm text-muted md:flex">
            <a href="#work" className="hover:text-ink">
              How it works
            </a>
            <a href="#features" className="hover:text-ink">
              Platform
            </a>
            <a href="#models" className="hover:text-ink">
              Free models
            </a>
            <a href="https://github.com/bozii/bozii" className="hover:text-ink">
              Source
            </a>
          </nav>
          <div className="flex items-center gap-2">
            <Link
              href="/auth?returnTo=%2Fdashboard"
              className="rounded-lg px-3 py-2 text-sm text-ink-2 hover:bg-surface-2"
            >
              Sign in
            </Link>
            <Link
              href="/auth?mode=signup&returnTo=%2Fdashboard"
              className="rounded-lg bg-graphite px-3.5 py-2 text-sm font-medium text-white hover:bg-black"
            >
              Get started
            </Link>
          </div>
        </div>
      </header>

      {/* ----------------------------------------------------------- hero */}
      <section className="relative overflow-hidden">
        <div className="hero-grid absolute inset-0" aria-hidden />
        <div className="relative mx-auto max-w-6xl px-5 pb-20 pt-16 sm:pt-24">
          <p className="kicker">Autonomous AI workforce</p>
          <h1 className="mt-4 max-w-3xl text-balance font-display text-4xl leading-[1.08] tracking-tight sm:text-6xl">
            Hire AI employees that do the work — and build the tools they are missing.
          </h1>
          <p className="mt-5 max-w-2xl text-pretty text-[17px] leading-relaxed text-ink-2">
            Bozii is an open-source platform for delegating real digital work: research, code, data,
            documents and browser tasks. Employees run a bounded execution loop with real tools, ask
            before consequential actions, and register whatever they invent as a tested, reusable
            capability.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/auth?mode=signup&returnTo=%2Fdashboard"
              className="inline-flex items-center gap-2 rounded-lg bg-graphite px-5 py-3 text-sm font-medium text-white hover:bg-black"
            >
              Start your workforce <ArrowRight size={16} />
            </Link>
            <a
              href="#work"
              className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-5 py-3 text-sm font-medium text-ink-2 hover:bg-surface-2"
            >
              See how it works
            </a>
          </div>
          <p className="mt-3 text-xs text-muted">
            Runs on free local models via Ollama — no paid API key required.
          </p>

          {/* live-looking task card */}
          <div className="mt-12 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="panel overflow-hidden">
              <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <span className="pulse-dot" /> Task · competitor research brief
                </div>
                <span className="rounded-full border border-teal-200 bg-accent-soft px-2 py-0.5 text-[10px] font-medium text-accent">
                  running
                </span>
              </div>
              <ul className="divide-y divide-line text-sm">
                {[
                  { t: "plan", m: "Plan created with 3 steps", tone: "text-info" },
                  { t: "tool", m: "web_search({ query: \"open source agent frameworks 2026\" })", tone: "text-ink-2" },
                  { t: "tool", m: "web_fetch(https://langchain-ai.github.io/…)", tone: "text-ink-2" },
                  { t: "tool", m: "write_file(report/draft.md)", tone: "text-ink-2" },
                  { t: "approval", m: "Waiting for approval: create_capability", tone: "text-warning" },
                ].map((row) => (
                  <li key={row.m} className="flex items-center gap-3 px-4 py-2.5">
                    <span className="w-16 shrink-0 text-[10px] uppercase tracking-wider text-faint">
                      {row.t}
                    </span>
                    <span className="log-row truncate text-muted">{row.m}</span>
                  </li>
                ))}
              </ul>
              <div className="border-t border-line bg-surface-2/60 px-4 py-2.5 text-xs text-muted">
                events streamed live from the execution engine · bounded to 12 iterations
              </div>
            </div>

            <div className="panel p-5">
              <p className="kicker">Self-extending capability</p>
              <ol className="mt-4 space-y-3.5">
                {PIPELINE.map((item) => (
                  <li key={item.step} className="flex gap-3">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-2 text-[10px] font-semibold text-muted">
                      {item.step}
                    </span>
                    <div>
                      <p className="text-sm font-medium">{item.title}</p>
                      <p className="text-[13px] leading-snug text-muted">{item.text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------- stats */}
      <section className="border-y border-line bg-surface">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-px px-5 sm:grid-cols-4">
          {STATS.map((stat) => (
            <div key={stat.label} className="px-2 py-7 text-center">
              <p className="text-3xl font-semibold tracking-tight tabular-nums">{stat.value}</p>
              <p className="mt-1 text-xs uppercase tracking-wider text-muted">{stat.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------- features */}
      <section id="features" className="mx-auto max-w-6xl px-5 py-20">
        <p className="kicker">The platform</p>
        <h2 className="mt-3 max-w-2xl text-balance font-display text-3xl tracking-tight sm:text-4xl">
          A workforce system: engine, tools, memory, permissions, observability.
        </h2>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => {
            const Icon = feature.icon;
            return (
              <div key={feature.title} className="panel p-5 transition-colors hover:border-line-strong">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-surface-2">
                  <Icon size={17} className="text-accent" />
                </div>
                <h3 className="mt-3.5 text-[15px] font-semibold">{feature.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{feature.text}</p>
              </div>
            );
          })}
        </div>
      </section>

      {/* -------------------------------------------------------- how it works */}
      <section id="work" className="border-y border-line bg-surface">
        <div className="mx-auto max-w-6xl px-5 py-20">
          <p className="kicker">Delegation loop</p>
          <h2 className="mt-3 max-w-2xl text-balance font-display text-3xl tracking-tight sm:text-4xl">
            Give an objective. Get a verified deliverable.
          </h2>
          <div className="mt-10 grid gap-6 md:grid-cols-4">
            {[
              { n: "1", t: "Assign", d: "Pick an employee, write the objective, set permissions and model." },
              { n: "2", t: "Plan & execute", d: "The engine plans, calls tools, inspects real output and recovers from errors." },
              { n: "3", t: "Approve", d: "Consequential actions suspend until you approve or deny them." },
              { n: "4", t: "Deliver", d: "Artifacts, a sourced report and a full event log you can replay." },
            ].map((step) => (
              <div key={step.n} className="relative">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-graphite text-xs font-semibold text-white">
                  {step.n}
                </div>
                <h3 className="mt-3 text-[15px] font-semibold">{step.t}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted">{step.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------- models */}
      <section id="models" className="mx-auto max-w-6xl px-5 py-20">
        <div className="grid items-center gap-10 lg:grid-cols-2">
          <div>
            <p className="kicker">Free by design</p>
            <h2 className="mt-3 text-balance font-display text-3xl tracking-tight sm:text-4xl">
              Local weights, hosted endpoints, no mandatory paid API.
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-ink-2">
              Point Bozii at Ollama and run open-weight models on your own hardware, or add any
              OpenAI-compatible endpoint — vLLM, llama.cpp, LiteLLM, a free-tier host. The model
              router checks tool support, context limits and availability, and fails with a clear
              message instead of pretending to work.
            </p>
            <ul className="mt-6 space-y-2.5 text-sm">
              {[
                "Ollama adapter with model discovery and capability probing",
                "OpenAI-compatible adapter for any self-hosted or remote endpoint",
                "Per-employee model, temperature and iteration limits",
                "Usage recorded per call — tokens, latency, failures",
              ].map((line) => (
                <li key={line} className="flex items-start gap-2 text-ink-2">
                  <Check size={15} className="mt-0.5 shrink-0 text-accent" />
                  {line}
                </li>
              ))}
            </ul>
          </div>
          <div className="panel overflow-hidden">
            <div className="border-b border-line px-4 py-2.5 text-xs font-medium text-muted">
              settings → models
            </div>
            <div className="divide-y divide-line text-sm">
              {[
                { name: "Ollama (local)", detail: "llama3.1:8b · qwen2.5:7b", state: "connected" },
                { name: "OpenAI-compatible", detail: "http://127.0.0.1:8080/v1", state: "connected" },
                { name: "Paid cloud API", detail: "not configured", state: "optional" },
              ].map((row) => (
                <div key={row.name} className="flex items-center justify-between px-4 py-3">
                  <div>
                    <p className="font-medium">{row.name}</p>
                    <p className="log-row text-muted">{row.detail}</p>
                  </div>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                      row.state === "connected"
                        ? "border-emerald-200 bg-success-soft text-success"
                        : "border-line bg-surface-2 text-muted"
                    }`}
                  >
                    {row.state}
                  </span>
                </div>
              ))}
            </div>
            <div className="border-t border-line bg-surface-2/60 px-4 py-3 text-xs text-muted">
              Free software ≠ free hosting. Self-host Bozii and the marginal cost is your own
              compute.
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------ cta */}
      <section className="border-t border-line bg-graphite text-white">
        <div className="mx-auto flex max-w-6xl flex-col items-start gap-6 px-5 py-16 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-balance font-display text-3xl tracking-tight">
              Put your backlog to work.
            </h2>
            <p className="mt-2 max-w-xl text-sm text-stone-400">
              Self-host the platform, connect a free model, hire your first employee in under five
              minutes.
            </p>
          </div>
          <div className="flex gap-3">
            <Link
              href="/auth?mode=signup&returnTo=%2Fdashboard"
              className="rounded-lg bg-white px-5 py-3 text-sm font-medium text-graphite hover:bg-stone-100"
            >
              Get started free
            </Link>
            <a
              href="https://github.com/bozii/bozii"
              className="rounded-lg border border-stone-600 px-5 py-3 text-sm font-medium text-white hover:bg-stone-800"
            >
              View source
            </a>
          </div>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-8 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Sparkles size={13} className="text-accent" />
            <span>Bozii — autonomous AI workforce platform. MIT licensed.</span>
          </div>
          <div className="flex gap-5">
            <a href="https://github.com/bozii/bozii" className="hover:text-ink">
              GitHub
            </a>
            <a href="https://github.com/bozii/bozii#readme" className="hover:text-ink">
              Docs
            </a>
            <Link href="/auth" className="hover:text-ink">
              Sign in
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}