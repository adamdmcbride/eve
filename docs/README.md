# Eve documentation

Status: canonical  
Last reviewed: 2026-08-23  
Current authority: public documentation front door  
Supersedes: none  
Superseded by: none

This is the public documentation map for Eve. Start with the smallest document
that answers the question you have; the public repository intentionally does
not publish private runtime evidence, personal continuity data, historical
operator notes, or internal coordination records.

## Start here

1. [Project overview](../README.md) — what Eve is, setup, privacy, and status.
2. [Architecture](ARCHITECTURE.md) — one Eve, five attention modes, durable
   state, model substrates, and governed organs.
3. [Eve Core](EVE_CORE.md) — identity, evidence, and behavior invariants.
4. [Executive scheduler](EXECUTIVE_SCHEDULER.md) — sparse cognition budgets and
   lane admission.
5. [Model lanes](model_lanes/README.md) — the five logical mode contracts.
6. [Autonomy policy](operating/AUTONOMY_POLICY.md) — permission, action, and
   verification boundaries.

## Build and evaluate

- [Contributing](../CONTRIBUTING.md)
- [Public route contracts](routing/README.md)
- [Hidden-test governance](evals/HIDDEN_TEST_GOVERNANCE.md)
- [Open-source overhaul roadmap](roadmaps/OPEN_SOURCE_OVERHAUL_2026_08_23.md)
- [Dependency license audit](evidence/DEPENDENCY_LICENSE_AUDIT_2026_08_23.md)
- [Public-release readiness audit](evidence/PUBLIC_RELEASE_READINESS_AUDIT_2026_08_23.md)

## Documentation boundaries

Files under `.eve/`, `.openclaw/`, runtime mirrors, generated OpenClaw memory,
model directories, training data, and local logs are data—not project
documentation. They are excluded from public exports.

The private development checkout contains additional evidence and historical
planning documents. Those files are deliberately omitted from the public tree
unless they are rewritten as portable, current, non-personal documentation.

When adding a public document:

- describe a current contract, not a private machine snapshot;
- use repository-relative links and portable paths;
- distinguish observed evidence from inference and aspiration;
- include the narrow verification command for behavioral claims;
- never include conversations, user profiles, credentials, model files, or
  hidden evaluation cases.
