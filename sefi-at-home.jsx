import { useState, useEffect, useRef } from "react";

// ═══════════════════════════════════════════════════════════════
// SEFI@Home — Search the Epstein Files Investigation
// Distributed Analysis Platform Design & Architecture Dashboard
// ═══════════════════════════════════════════════════════════════

// Scaling behaviors describe how analytical value changes with batch size.
// "linear"      — 10x data = ~10x findings. Each item is independent. Batch for efficiency only.
// "multiplying" — 10x data = 30-100x insight. Patterns, graphs, and clusters emerge at concentration.
// "plateau"     — Returns multiply up to a threshold, then flatten. There's a sweet spot.
// "aggregation" — Individual units are extract-only. Value multiplies in a SEPARATE aggregation pass.

const WORK_UNIT_TYPES = [
  {
    id: "gap_analysis",
    name: "Gap Analysis",
    icon: "🕳️",
    description: "Identify missing documents by analyzing EFTA number sequences and cross-references",
    difficulty: "low",
    inputType: "EFTA range",
    outputType: "Gap report with missing document IDs and context",
    exampleQuery: "SELECT efta_number FROM pages WHERE dataset=9 ORDER BY efta_number — find discontinuities",
    estimatedTokens: "~2K per range of 1,000 docs",
    scaling: "linear",
    scalingNote: "Checking 100 vs 1,000 EFTA numbers is proportional work. Batch size is a convenience choice, not an analytical one.",
    optimalBatch: "1,000 EFTA numbers",
    path: 2,
  },
  {
    id: "cross_ref_audit",
    name: "Cross-Reference Audit",
    icon: "🔗",
    description: "When Document A mentions Document B, verify Document B exists in the corpus",
    difficulty: "medium",
    inputType: "Page text with document references",
    outputType: "Citation graph edges + missing node list",
    exampleQuery: "Find all mentions of EFTA numbers, case numbers, or Bates stamps within page text",
    estimatedTokens: "~5K per 50 pages → ~20K per 500 pages",
    scaling: "plateau",
    scalingNote: "At 50 pages you find individual citations. At 500 pages from the same dataset, citation CLUSTERS emerge — groups of documents referencing each other reveal investigative threads. Beyond 1,000 pages, new insight per page drops off.",
    optimalBatch: "500 pages from a single dataset",
    path: 2,
  },
  {
    id: "document_classify",
    name: "Document Classification",
    icon: "📋",
    description: "Classify each document by type: email, FBI 302, police report, financial record, court filing, etc.",
    difficulty: "low",
    inputType: "First 500 chars of document text",
    outputType: "Document type label + confidence score",
    exampleQuery: "Given page 1 text, classify as one of 24 document types per EFTA taxonomy",
    estimatedTokens: "~1K per document, batchable to 20",
    scaling: "linear",
    scalingNote: "Document N gives no help classifying document N+1. Batch 10-20 into one prompt to amortize overhead, but accuracy is the same either way.",
    optimalBatch: "20 documents per prompt",
    path: 2,
  },
  {
    id: "npa_timeline",
    name: "NPA Timeline Extraction",
    icon: "⚖️",
    description: "Extract dates, actors, and decisions from non-prosecution agreement correspondence",
    difficulty: "high",
    inputType: "DS9 pages mentioning NPA/plea/immunity keywords",
    outputType: "Structured timeline events with EFTA citations",
    exampleQuery: "Extract: date, author, recipient, decision/action, rationale from NPA-related memos",
    estimatedTokens: "~8K per document (full context needed)",
    scaling: "aggregation",
    scalingNote: "Each memo is a self-contained extraction task — bigger batches don't improve extraction. But the timeline only becomes meaningful when a SEPARATE aggregation pass assembles individually-extracted events in chronological order. The aggregation unit is where the multiplying returns live.",
    optimalBatch: "1 document per extraction unit, then 50+ events per aggregation unit",
    path: 3,
  },
  {
    id: "decision_chain",
    name: "Decision Chain Mapping",
    icon: "🗺️",
    description: "Map who communicated with whom about prosecution decisions, and when",
    difficulty: "high",
    inputType: "Internal DOJ correspondence in DS9",
    outputType: "Communication graph: sender → recipient → topic → date",
    exampleQuery: "From email headers and memo headers, extract the decision-maker network — batch 20+ from the same month to see who was CC'd, who responded, who was absent",
    estimatedTokens: "~30-40K per batch of 20 documents from the same time window",
    scaling: "multiplying",
    scalingNote: "One memo tells you Acosta sent it. Twenty memos from the same month reveal who was CC'd, who responded, who was notably absent. The network only becomes visible with enough nodes. Single documents are nearly useless here.",
    optimalBatch: "20-50 documents from the same 30-day period",
    path: 3,
  },
  {
    id: "entity_extraction",
    name: "Financial Entity NER",
    icon: "🏦",
    description: "Extract financial entities: bank names, account refs, wire amounts, corporate shells",
    difficulty: "medium",
    inputType: "Pages containing financial keywords",
    outputType: "Structured entity records with amounts, dates, and relationships",
    exampleQuery: "Extract all (entity, amount, date, counterparty) tuples from financial documents",
    estimatedTokens: "~4K per batch of 20 pages",
    scaling: "aggregation",
    scalingNote: "Extraction per page is independent — bigger batches don't find more entities per page. But entity DEDUPLICATION and LINKING (is 'Southern Financial' the same as 'Southern Trust Co Inc'?) requires a separate aggregation pass across hundreds of extraction results.",
    optimalBatch: "20 pages per extraction, then 200+ records per deduplication pass",
    path: 4,
  },
  {
    id: "money_flow",
    name: "Money Flow Tracing",
    icon: "💰",
    description: "Trace money movement between entities across multiple documents",
    difficulty: "high",
    inputType: "Financial entity records from entity_extraction units",
    outputType: "Directed graph edges: source → amount → destination with temporal ordering",
    exampleQuery: "Given extracted wire transfers, reconstruct the flow: who paid whom, when, how much. With 100+ transactions, look for the same intermediary appearing in 30% of flows, or timing clusters around legal events.",
    estimatedTokens: "~20K per batch of 50-100 transactions",
    scaling: "multiplying",
    scalingNote: "10 transactions might show 2 complete chains. 100 transactions reveal PATTERNS — the same intermediary in 30% of flows, or timing clusters around legal events. 1,000 transactions map the entire financial topology. Each new transaction adds edges to a graph whose analytical value grows combinatorially.",
    optimalBatch: "50-100 transactions with overlapping time windows",
    path: 4,
  },
  {
    id: "shell_mapping",
    name: "Shell Company Mapping",
    icon: "🏢",
    description: "Link corporate entities to beneficial owners and identify entity clusters",
    difficulty: "medium",
    inputType: "Corporate entity mentions across full corpus",
    outputType: "Entity ownership graph with confidence scores",
    exampleQuery: "Cross-reference entity names against the 95+ known shells in SHELL_ENTITY_MAP",
    estimatedTokens: "~3K per entity cluster",
    scaling: "plateau",
    scalingNote: "Linking one shell to its owner is useful. Linking 10 shells reveals a cluster under common control. Linking 50 hits diminishing returns because the cluster structure is already clear. The 95+ known shells are the plateau ceiling.",
    optimalBatch: "10-20 related entity mentions",
    path: 4,
  },
  {
    id: "redaction_compare",
    name: "Redaction Consistency Check",
    icon: "⬛",
    description: "Compare ALL versions of a document to find asymmetric redactions",
    difficulty: "medium",
    inputType: "All duplicate versions of one document from redaction_analysis_v2.db",
    outputType: "Diff report: what's redacted in version A but visible in versions B-F",
    exampleQuery: "For a document appearing 6 times (like the NPR PowerPoint), compare hidden_text at same coordinates across ALL versions simultaneously — not pairwise",
    estimatedTokens: "~8K per document (all versions together)",
    scaling: "plateau",
    scalingNote: "Comparing one pair finds one inconsistency. Comparing ALL versions of the same document (NPR found one with 6 copies) reveals the full redaction strategy — which names were protected in which releases. The unit must be 'all known duplicates' rather than 'one pair.' Returns plateau at the duplicate count.",
    optimalBatch: "All known versions of one document (typically 2-6)",
    path: 1,
  },
  {
    id: "verify_finding",
    name: "Finding Verification",
    icon: "✅",
    description: "Independently verify a claim from the Epstein-research reports against source documents",
    difficulty: "low",
    inputType: "Claim + cited EFTA numbers",
    outputType: "Verified / Disputed / Insufficient Evidence + reasoning",
    exampleQuery: "Report claims X based on EFTA00090314. Read the document. Does it support the claim?",
    estimatedTokens: "~4K per claim",
    scaling: "linear",
    scalingNote: "Each claim is atomic. Verifying claim X doesn't help verify claim Y. This is the one task where single-unit contributions are just as valuable per-token as bulk work.",
    optimalBatch: "1 claim per unit",
    path: 5,
  },
];

const ARCHITECTURE = {
  layers: [
    {
      name: "Data Layer",
      color: "#1a1a2e",
      components: [
        { name: "full_text_corpus.db", size: "6.08 GB", desc: "1.38M docs, 2.73M pages" },
        { name: "redaction_analysis_v2.db", size: "0.95 GB", desc: "2.59M redaction records" },
        { name: "transcripts.db", size: "2.5 MB", desc: "1,530 audio/video transcripts" },
        { name: "knowledge_graph.db", size: "—", desc: "524 entities, 2,096 connections" },
      ],
    },
    {
      name: "Work Unit Generator",
      color: "#16213e",
      components: [
        { name: "Range Partitioner", desc: "Splits EFTA ranges into analyzable chunks — batch size varies by scaling type" },
        { name: "Query Materializer", desc: "Pre-runs SQL to extract page text for each unit" },
        { name: "Dependency Resolver", desc: "Chains units (extract → aggregate) and groups multiplying tasks by time window" },
        { name: "Priority Scorer", desc: "Ranks units by expected information yield — prefers multiplying tasks at concentration" },
      ],
    },
    {
      name: "Distribution API",
      color: "#0f3460",
      components: [
        { name: "GET /work", desc: "Claim a work unit (type, difficulty, data slice)" },
        { name: "POST /result", desc: "Submit analysis result with provenance chain" },
        { name: "GET /status", desc: "Project stats, leaderboard, coverage map" },
        { name: "POST /dispute", desc: "Flag a result for re-analysis by another worker" },
      ],
    },
    {
      name: "Validation Layer",
      color: "#533483",
      components: [
        { name: "Quorum Validator", desc: "N-of-M agreement before accepting results" },
        { name: "Consistency Checker", desc: "Cross-checks against known-good data" },
        { name: "PII Guardian", desc: "Blocks results containing victim-identifying info" },
        { name: "Provenance Logger", desc: "Every finding traces to EFTA doc + page" },
      ],
    },
    {
      name: "Output Layer",
      color: "#2a2035",
      components: [
        { name: "Findings DB", desc: "Structured, searchable investigation results" },
        { name: "Coverage Dashboard", desc: "What % of corpus has been analyzed per type" },
        { name: "Public API", desc: "Other tools can query SEFI findings" },
        { name: "GitHub Sync", desc: "Auto-publish verified findings as reports" },
      ],
    },
  ],
};

const ETHICAL_CONSTRAINTS = [
  { rule: "PII Guardian runs on ALL outputs before acceptance", icon: "🛡️" },
  { rule: "No work units involve images or video (text-only analysis)", icon: "📝" },
  { rule: "Victim names detected in output → unit quarantined + reported to EFTA@usdoj.gov", icon: "🚨" },
  { rule: "All results are public domain (federal government source material)", icon: "📂" },
  { rule: "Quorum of 3 required for any finding involving named individuals", icon: "👥" },
  { rule: "Unverified FBI tips clearly labeled — never treated as established fact", icon: "⚠️" },
  { rule: "No attempt to de-anonymize redactions — analysis of redaction patterns only", icon: "⬛" },
];

// ── Animated counter ──
function AnimCounter({ end, duration = 2000, prefix = "", suffix = "" }) {
  const [val, setVal] = useState(0);
  const ref = useRef(null);
  useEffect(() => {
    const obs = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          const start = performance.now();
          const tick = (now) => {
            const p = Math.min((now - start) / duration, 1);
            const ease = 1 - Math.pow(1 - p, 3);
            setVal(Math.floor(ease * end));
            if (p < 1) requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
          obs.disconnect();
        }
      },
      { threshold: 0.3 }
    );
    if (ref.current) obs.observe(ref.current);
    return () => obs.disconnect();
  }, [end, duration]);
  return <span ref={ref}>{prefix}{val.toLocaleString()}{suffix}</span>;
}

// ── Work Unit Card ──
function WorkUnitCard({ unit, isExpanded, onToggle }) {
  // Colorblind-safe palette: blue / amber / magenta (avoids red-green confusion)
  const diffColor = { low: "#3b82f6", medium: "#f59e0b", high: "#d946ef" };
  const diffShape = { low: "●", medium: "◆", high: "▲" };
  const scalingColor = { linear: "#3b82f6", multiplying: "#d946ef", plateau: "#f59e0b", aggregation: "#14b8a6" };
  const scalingIcon = { linear: "━", multiplying: "📈", plateau: "⏸", aggregation: "🧩" };
  const pathLabel = { 1: "Redaction Audit", 2: "Gap Analysis", 3: "NPA Forensics", 4: "Financial Network", 5: "Verification" };
  return (
    <div
      onClick={onToggle}
      style={{
        background: "rgba(255,255,255,0.03)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 12,
        padding: "20px 24px",
        cursor: "pointer",
        transition: "all 0.3s ease",
        borderLeft: `3px solid ${diffColor[unit.difficulty]}`,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.06)"; e.currentTarget.style.transform = "translateY(-2px)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.03)"; e.currentTarget.style.transform = "translateY(0)"; }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <span style={{ fontSize: 28 }}>{unit.icon}</span>
          <div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 15, fontWeight: 600, color: "#e0e0e0" }}>{unit.name}</div>
            <div style={{ fontSize: 12, color: "#aaa", marginTop: 2 }}>{unit.description}</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.5,
            color: diffColor[unit.difficulty], background: `${diffColor[unit.difficulty]}15`,
            padding: "3px 8px", borderRadius: 4,
          }}>{diffShape[unit.difficulty]} {unit.difficulty}</span>
          <span style={{
            fontSize: 10, fontWeight: 600, color: "#a78bfa", background: "rgba(167,139,250,0.1)",
            padding: "3px 8px", borderRadius: 4,
          }}>Path {unit.path}</span>
        </div>
      </div>
      {isExpanded && (
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid rgba(255,255,255,0.06)" }}>
          {/* Scaling behavior badge — prominent */}
          <div style={{
            display: "flex", alignItems: "center", gap: 10, marginBottom: 14,
            background: `${scalingColor[unit.scaling]}10`, border: `1px solid ${scalingColor[unit.scaling]}30`,
            borderRadius: 8, padding: "10px 14px",
          }}>
            <span style={{ fontSize: 18 }}>{scalingIcon[unit.scaling]}</span>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: scalingColor[unit.scaling], textTransform: "uppercase", letterSpacing: 1 }}>
                {unit.scaling} returns
              </div>
              <div style={{ fontSize: 12, color: "#ccc", marginTop: 3, lineHeight: 1.6 }}>
                {unit.scalingNote}
              </div>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {[
              ["Input", unit.inputType],
              ["Output", unit.outputType],
              ["Est. Cost", unit.estimatedTokens],
              ["Optimal Batch", unit.optimalBatch],
              ["Research Path", pathLabel[unit.path]],
            ].map(([label, value]) => (
              <div key={label}>
                <div style={{ fontSize: 10, color: "#666", textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: 13, color: "#ccc", fontFamily: "'JetBrains Mono', monospace" }}>{value}</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 10, color: "#666", textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>Example Query</div>
            <code style={{
              display: "block", fontSize: 12, color: "#a78bfa", background: "rgba(167,139,250,0.08)",
              padding: "10px 14px", borderRadius: 6, fontFamily: "'JetBrains Mono', monospace",
              lineHeight: 1.6, whiteSpace: "pre-wrap",
            }}>{unit.exampleQuery}</code>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Architecture Layer ──
function ArchLayer({ layer, index }) {
  return (
    <div style={{
      background: layer.color,
      borderRadius: 10,
      padding: "18px 22px",
      position: "relative",
      animation: `fadeSlideIn 0.5s ease ${index * 0.1}s both`,
    }}>
      <div style={{
        position: "absolute", top: -10, left: 20,
        fontSize: 10, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase",
        color: "#fff", background: layer.color, padding: "2px 10px", borderRadius: 4,
        border: "1px solid rgba(255,255,255,0.15)",
      }}>{layer.name}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginTop: 8 }}>
        {layer.components.map((c) => (
          <div key={c.name} style={{
            background: "rgba(255,255,255,0.12)", borderRadius: 6, padding: "10px 14px",
            border: "1px solid rgba(255,255,255,0.10)",
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#f0f0f0", fontFamily: "'JetBrains Mono', monospace" }}>{c.name}</div>
            {c.size && <div style={{ fontSize: 11, color: "#f59e0b", marginTop: 2 }}>{c.size}</div>}
            <div style={{ fontSize: 12, color: "#ccc", marginTop: 2, lineHeight: 1.6 }}>{c.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── JSON Schema Preview ──
function SchemaPreview() {
  const schema = `// GET /work — Claim a work unit
{
  "unit_id": "gap-ds9-039025-040000",
  "type": "gap_analysis",
  "path": 2,
  "difficulty": "low",
  "scaling": "linear",
  "optimal_batch": "1,000 EFTA numbers",
  "input": {
    "database": "full_text_corpus.db",
    "query": "SELECT efta_number FROM pages WHERE efta_number BETWEEN 39025 AND 40000 ORDER BY efta_number",
    "context": "DS9 range — email evidence dataset"
  },
  "instructions": "Identify all gaps in EFTA numbering. For each gap, check if adjacent documents reference the missing numbers. Report: gap_start, gap_end, gap_size, adjacent_context.",
  "constraints": {
    "max_output_tokens": 2000,
    "pii_filter": true,
    "requires_quorum": false
  },
  "deadline": "2026-02-16T00:00:00Z"
}

// POST /result — Submit findings
{
  "unit_id": "gap-ds9-039025-040000",
  "worker_id": "claude-session-abc123",
  "result": {
    "gaps_found": 14,
    "gaps": [
      {
        "start": 39187, "end": 39201, "size": 14,
        "adjacent_before": "EFTA00039186: Email re: NPA discussion",
        "adjacent_after": "EFTA00039202: FBI 302 interview",
        "assessment": "Gap falls within NPA correspondence sequence — potentially withheld deliberative material"
      }
    ],
    "coverage": { "range_start": 39025, "range_end": 40000, "total_present": 961, "total_missing": 14 }
  },
  "provenance": {
    "model": "claude-opus-4-6",
    "timestamp": "2026-02-15T18:30:00Z",
    "session_tokens_used": 1847
  }
}`;
  return (
    <pre style={{
      background: "#0d1117",
      border: "1px solid rgba(255,255,255,0.08)",
      borderRadius: 10,
      padding: 24,
      fontSize: 12,
      lineHeight: 1.7,
      color: "#8b949e",
      fontFamily: "'JetBrains Mono', monospace",
      overflow: "auto",
      maxHeight: 500,
    }}>
      {schema.split("\n").map((line, i) => {
        let color = "#8b949e";
        if (line.trim().startsWith("//")) color = "#6a9955";
        else if (line.includes('":')) color = "#9cdcfe";
        else if (/"[^"]*"/.test(line) && !line.includes(":")) color = "#ce9178";
        return <div key={i} style={{ color }}>{line}</div>;
      })}
    </pre>
  );
}

// ── Contribution Flow Diagram ──
function ContributionFlow() {
  const steps = [
    { icon: "📥", label: "Claim Unit", desc: "Worker requests a work unit via API" },
    { icon: "🗄️", label: "Receive Data", desc: "Pre-materialized text slice (no raw DB needed)" },
    { icon: "🧠", label: "Analyze", desc: "LLM or human processes the text per instructions" },
    { icon: "📤", label: "Submit Result", desc: "Structured JSON with EFTA provenance" },
    { icon: "🔍", label: "Validate", desc: "Quorum check + PII filter + consistency" },
    { icon: "✅", label: "Accept/Dispute", desc: "Merged into findings DB or flagged for re-work" },
  ];
  return (
    <div style={{ display: "flex", gap: 4, alignItems: "stretch", flexWrap: "wrap" }}>
      {steps.map((s, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 4, flex: "1 1 auto", minWidth: 140 }}>
          <div style={{
            background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 10, padding: "14px 16px", textAlign: "center", flex: 1,
            animation: `fadeSlideIn 0.4s ease ${i * 0.08}s both`,
          }}>
            <div style={{ fontSize: 24, marginBottom: 6 }}>{s.icon}</div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#e0e0e0", letterSpacing: 0.5 }}>{s.label}</div>
            <div style={{ fontSize: 10, color: "#aaa", marginTop: 4, lineHeight: 1.4 }}>{s.desc}</div>
          </div>
          {i < steps.length - 1 && <span style={{ color: "#444", fontSize: 16, flexShrink: 0 }}>→</span>}
        </div>
      ))}
    </div>
  );
}

// ── Difference from BOINC callout ──
function BoincDiff() {
  const diffs = [
    { boinc: "Distributes FLOPS (raw compute)", sefi: "Distributes ANALYSIS (structured reasoning)" },
    { boinc: "Workers run compiled binaries", sefi: "Workers are LLMs or humans with SQL access" },
    { boinc: "Results are numeric outputs", sefi: "Results are structured findings with citations" },
    { boinc: "Validation = bitwise comparison", sefi: "Validation = semantic quorum + PII filter" },
    { boinc: "Workers need full dataset locally", sefi: "Workers receive pre-sliced text (no 6GB download)" },
    { boinc: "Credit = FLOPS contributed", sefi: "Credit = verified findings + coverage %" },
    { boinc: "All work units scale the same way", sefi: "Scaling varies: linear, multiplying, plateau, or aggregation — bigger bites sometimes yield exponentially more insight" },
  ];
  return (
    <div style={{ display: "grid", gap: 1, borderRadius: 10, overflow: "hidden", border: "1px solid rgba(255,255,255,0.08)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, background: "rgba(255,255,255,0.04)" }}>
        <div style={{ padding: "10px 16px", fontSize: 11, fontWeight: 700, color: "#aaa", letterSpacing: 1, textTransform: "uppercase" }}>SETI@Home / BOINC</div>
        <div style={{ padding: "10px 16px", fontSize: 11, fontWeight: 700, color: "#a78bfa", letterSpacing: 1, textTransform: "uppercase" }}>SEFI@Home</div>
      </div>
      {diffs.map((d, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1 }}>
          <div style={{ padding: "10px 16px", fontSize: 12, color: "#aaa", background: "rgba(255,255,255,0.02)", borderTop: "1px solid rgba(255,255,255,0.04)" }}>{d.boinc}</div>
          <div style={{ padding: "10px 16px", fontSize: 12, color: "#e0e0e0", background: "rgba(167,139,250,0.04)", borderTop: "1px solid rgba(255,255,255,0.04)" }}>{d.sefi}</div>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════
export default function SEFIHome() {
  const [expandedUnit, setExpandedUnit] = useState(null);
  const [activeSection, setActiveSection] = useState("overview");

  const sections = [
    { id: "overview", label: "Overview" },
    { id: "architecture", label: "Architecture" },
    { id: "work-units", label: "Work Units" },
    { id: "api", label: "API Schema" },
    { id: "ethics", label: "Ethics" },
    { id: "contribute", label: "Contribute" },
  ];

  return (
    <div style={{
      background: "#0a0a0f",
      color: "#e0e0e0",
      minHeight: "100vh",
      fontFamily: "'Atkinson Hyperlegible', 'Verdana', system-ui, -apple-system, sans-serif",
      fontSize: 16,
      lineHeight: 1.8,
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
        @keyframes fadeSlideIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
        @keyframes scanline { 0% { transform: translateY(-100%); } 100% { transform: translateY(100vh); } }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0a0a0f; }
        ::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
        /* Dyslexia-friendly: wider letter and word spacing */
        p, span, div { letter-spacing: 0.02em; word-spacing: 0.08em; }
      `}</style>

      {/* ── Scanline effect ── */}
      <div style={{
        position: "fixed", top: 0, left: 0, right: 0, bottom: 0, pointerEvents: "none", zIndex: 100,
        background: "repeating-linear-gradient(0deg, rgba(255,255,255,0.008) 0px, rgba(255,255,255,0.008) 1px, transparent 1px, transparent 3px)",
      }} />

      {/* ── Nav ── */}
      <nav style={{
        position: "sticky", top: 0, zIndex: 50,
        background: "rgba(10,10,15,0.9)", backdropFilter: "blur(20px)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        padding: "0 32px",
      }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", alignItems: "center", height: 56 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginRight: 40 }}>
            <span style={{ fontSize: 20 }}>📡</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, fontSize: 14, letterSpacing: 2, color: "#a78bfa" }}>SEFI@HOME</span>
            <span style={{ animation: "pulse 2s infinite", width: 6, height: 6, borderRadius: "50%", background: "#3b82f6", display: "inline-block" }} title="System active" />
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            {sections.map((s) => (
              <button
                key={s.id}
                onClick={() => { setActiveSection(s.id); document.getElementById(s.id)?.scrollIntoView({ behavior: "smooth" }); }}
                style={{
                  background: activeSection === s.id ? "rgba(167,139,250,0.15)" : "transparent",
                  border: "none", color: activeSection === s.id ? "#a78bfa" : "#aaa",
                  padding: "8px 14px", borderRadius: 6, fontSize: 12, fontWeight: 600,
                  cursor: "pointer", fontFamily: "'Atkinson Hyperlegible', 'Verdana', sans-serif",
                  transition: "all 0.2s ease",
                }}
              >{s.label}</button>
            ))}
          </div>
        </div>
      </nav>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "0 32px 80px" }}>

        {/* ══ HERO ══ */}
        <section id="overview" style={{ padding: "80px 0 60px" }}>
          <div style={{ animation: "fadeSlideIn 0.6s ease" }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 3, color: "#a78bfa", textTransform: "uppercase", marginBottom: 16 }}>Distributed Investigation Platform</div>
            <h1 style={{
              fontSize: 48, fontWeight: 700, lineHeight: 1.1, letterSpacing: -1,
              background: "linear-gradient(135deg, #e0e0e0 30%, #a78bfa 70%)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
              maxWidth: 700,
            }}>
              Search the Epstein Files Investigation
            </h1>
            <p style={{ fontSize: 16, color: "#b0b0b0", marginTop: 20, maxWidth: 650, lineHeight: 1.8 }}>
              A BOINC-inspired distributed analysis system where volunteers donate <strong style={{ color: "#e0e0e0" }}>reasoning tokens</strong> instead of CPU cycles. Work units break 3.18 billion characters of DOJ documents into analyzable chunks. LLMs and humans contribute structured findings that trace back to source documents. <strong style={{ color: "#a78bfa" }}>Not all tasks scale equally</strong> — some yield proportional returns at any size, while others only become insightful (and personally rewarding) at higher concentration, where patterns, networks, and gaps emerge from the data.
            </p>
          </div>

          {/* Stats */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginTop: 48 }}>
            {[
              { value: 1380937, label: "Documents", suffix: "" },
              { value: 2731785, label: "Pages", suffix: "" },
              { value: 3180, label: "Characters", suffix: "M" },
              { value: 10, label: "Work Unit Types", suffix: "" },
            ].map((s) => (
              <div key={s.label} style={{
                background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 10, padding: "20px 22px", textAlign: "center",
              }}>
                <div style={{ fontSize: 28, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: "#a78bfa" }}>
                  <AnimCounter end={s.value} />{s.suffix}
                </div>
                <div style={{ fontSize: 11, color: "#aaa", marginTop: 6, textTransform: "uppercase", letterSpacing: 1 }}>{s.label}</div>
              </div>
            ))}
          </div>
        </section>

        {/* ══ KEY DIFFERENCE ══ */}
        <section style={{ padding: "40px 0" }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#e0e0e0", marginBottom: 6 }}>Not BOINC — Something New</h2>
          <p style={{ fontSize: 13, color: "#aaa", marginBottom: 20, maxWidth: 600 }}>
            SETI@home distributed compute. SEFI@Home distributes investigation. The fundamental unit isn't a FLOP — it's a finding.
          </p>
          <BoincDiff />
        </section>

        {/* ══ ARCHITECTURE ══ */}
        <section id="architecture" style={{ padding: "60px 0" }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#e0e0e0", marginBottom: 6 }}>System Architecture</h2>
          <p style={{ fontSize: 13, color: "#aaa", marginBottom: 28 }}>Five layers from data to published findings. Workers interact only with the Distribution API — no direct database access required.</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            {ARCHITECTURE.layers.map((layer, i) => (
              <ArchLayer key={layer.name} layer={layer} index={i} />
            ))}
          </div>
        </section>

        {/* ══ CONTRIBUTION FLOW ══ */}
        <section style={{ padding: "40px 0" }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#e0e0e0", marginBottom: 6 }}>How Contribution Works</h2>
          <p style={{ fontSize: 13, color: "#aaa", marginBottom: 20 }}>Every analysis session follows the same six-step flow — whether you're a Claude instance, a GPT session, or a human researcher.</p>
          <ContributionFlow />
        </section>

        {/* ══ WORK UNITS ══ */}
        <section id="work-units" style={{ padding: "60px 0" }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#e0e0e0", marginBottom: 6 }}>Work Unit Catalog</h2>
          <p style={{ fontSize: 13, color: "#aaa", marginBottom: 28 }}>10 unit types across 5 research paths. Click to expand. Each unit is self-contained — workers don't need to understand the full investigation.</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {WORK_UNIT_TYPES.map((unit) => (
              <WorkUnitCard
                key={unit.id}
                unit={unit}
                isExpanded={expandedUnit === unit.id}
                onToggle={() => setExpandedUnit(expandedUnit === unit.id ? null : unit.id)}
              />
            ))}
          </div>
        </section>

        {/* ══ API SCHEMA ══ */}
        <section id="api" style={{ padding: "60px 0" }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#e0e0e0", marginBottom: 6 }}>API Schema</h2>
          <p style={{ fontSize: 13, color: "#aaa", marginBottom: 20 }}>The critical design choice: workers receive pre-materialized text, not raw SQL access. This means contributors don't need the 6GB database — just an HTTP client.</p>
          <SchemaPreview />
        </section>

        {/* ══ ETHICS ══ */}
        <section id="ethics" style={{ padding: "60px 0" }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#e0e0e0", marginBottom: 6 }}>Ethical Constraints — Hardcoded, Not Optional</h2>
          <p style={{ fontSize: 13, color: "#aaa", marginBottom: 20 }}>These aren't guidelines. They're validation layer rules that reject non-compliant results automatically.</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {ETHICAL_CONSTRAINTS.map((c, i) => (
              <div key={i} style={{
                display: "flex", gap: 14, alignItems: "center",
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 8, padding: "14px 18px",
                animation: `fadeSlideIn 0.4s ease ${i * 0.05}s both`,
              }}>
                <span style={{ fontSize: 20, flexShrink: 0 }}>{c.icon}</span>
                <span style={{ fontSize: 13, color: "#ccc", fontFamily: "'JetBrains Mono', monospace" }}>{c.rule}</span>
              </div>
            ))}
          </div>
        </section>

        {/* ══ CONTRIBUTE ══ */}
        <section id="contribute" style={{ padding: "60px 0" }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#e0e0e0", marginBottom: 6 }}>How to Contribute</h2>
          <p style={{ fontSize: 13, color: "#aaa", marginBottom: 8 }}>Three concentration levels. Deeper engagement unlocks the tasks where insight multiplies.</p>
          <p style={{ fontSize: 12, color: "#aaa", marginBottom: 28, lineHeight: 1.7 }}>
            Some tasks (classification, verification) are just as valuable in single units. Others (financial flows, decision chains) only become rewarding — analytically and personally — when you can see enough of the picture to find the patterns yourself. Choose your level based on how deep you want to go.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
            {[
              {
                tier: "Sampler",
                icon: "💬",
                color: "#3b82f6",
                scalingTypes: "Linear tasks",
                items: [
                  "Paste a work unit into any LLM chat",
                  "Best for: classification, gap analysis, verification",
                  "These are LINEAR tasks — each unit is self-contained",
                  "~5 minutes per unit, no setup",
                  "Every unit moves the coverage needle",
                ],
              },
              {
                tier: "Investigator",
                icon: "🔍",
                color: "#f59e0b",
                scalingTypes: "Plateau + aggregation tasks",
                items: [
                  "Claim batches of related units (same dataset, time window, or entity)",
                  "Best for: cross-references, redaction audits, entity deduplication",
                  "These tasks reward CONCENTRATION — patterns emerge at 50-500 items",
                  "You start seeing things no single unit reveals",
                  "Most volunteers find this is where it gets personally compelling",
                ],
              },
              {
                tier: "Analyst",
                icon: "🧠",
                color: "#a78bfa",
                scalingTypes: "Multiplying tasks",
                items: [
                  "Run sustained sessions on network-type tasks",
                  "Best for: money flows, decision chains, shell company mapping",
                  "These tasks have MULTIPLYING returns — 10x data = 30-100x insight",
                  "You're building graph structure where each edge makes every other edge more meaningful",
                  "This is where original findings happen",
                ],
              },
            ].map((t) => (
              <div key={t.tier} style={{
                background: "rgba(255,255,255,0.03)",
                border: `1px solid ${t.color}30`,
                borderRadius: 12, padding: 24,
                borderTop: `3px solid ${t.color}`,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                  <span style={{ fontSize: 24 }}>{t.icon}</span>
                  <span style={{ fontSize: 16, fontWeight: 700, color: t.color }}>{t.tier}</span>
                </div>
                <div style={{ fontSize: 10, color: t.color, opacity: 0.7, letterSpacing: 1, textTransform: "uppercase", marginBottom: 16 }}>{t.scalingTypes}</div>
                {t.items.map((item, i) => (
                  <div key={i} style={{ fontSize: 12, color: "#aaa", padding: "6px 0", borderBottom: i < t.items.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none", lineHeight: 1.5 }}>
                    {item}
                  </div>
                ))}
              </div>
            ))}
          </div>

          {/* Call to action */}
          <div style={{
            marginTop: 48, padding: "32px 36px",
            background: "linear-gradient(135deg, rgba(167,139,250,0.08), rgba(233,69,96,0.06))",
            border: "1px solid rgba(167,139,250,0.2)",
            borderRadius: 14,
          }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#e0e0e0", marginBottom: 8 }}>This is a design document, not a deployed system — yet.</div>
            <div style={{ fontSize: 13, color: "#aaa", lineHeight: 1.7, maxWidth: 700 }}>
              The databases exist. The research paths are defined. The work unit types are specified. What's needed is someone to build the Distribution API and Validation Layer — probably a weekend project with FastAPI + SQLite. The hardest part is already done by rhowardstone. This architecture just makes their data accessible to distributed volunteer analysis.
            </div>
            <div style={{ marginTop: 16, display: "flex", gap: 12 }}>
              <a href="https://github.com/rhowardstone/Epstein-research-data" target="_blank" rel="noopener noreferrer" style={{
                display: "inline-block", padding: "10px 20px", background: "rgba(167,139,250,0.2)",
                border: "1px solid rgba(167,139,250,0.4)", borderRadius: 8,
                color: "#a78bfa", fontSize: 13, fontWeight: 600, textDecoration: "none",
                fontFamily: "'JetBrains Mono', monospace",
              }}>Source Databases →</a>
              <a href="https://github.com/rhowardstone/Epstein-research" target="_blank" rel="noopener noreferrer" style={{
                display: "inline-block", padding: "10px 20px", background: "rgba(255,255,255,0.05)",
                border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8,
                color: "#e0e0e0", fontSize: 13, fontWeight: 600, textDecoration: "none",
                fontFamily: "'JetBrains Mono', monospace",
              }}>Forensic Reports →</a>
            </div>
          </div>
        </section>

      </div>
    </div>
  );
}
