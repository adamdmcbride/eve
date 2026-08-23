# Eve Rust Kernel

This directory is the beginning of Eve's long-term infrastructure layer.

Right now Eve's cognition and most runtime behavior still live in Python. That is intentional. The goal here is not a rewrite. The goal is to establish the lowest-level system pieces in Rust first, where long-lived processes, supervision, concurrency, and future multi-node coordination belong.

## Current Scope

The first crate is:

- `eve-kernel`
  - a minimal local HTTP service
  - stdlib-only on purpose
  - reads Eve's current on-disk runtime state
  - exposes health and status endpoints

This is the earliest safe slice of the future kernel.

The kernel is being designed as cross-platform infrastructure from the start, not a macOS daemon rewritten in Rust later.

## Planned Direction

The Rust layer should eventually own:

1. process supervision
2. runtime API core
3. durable event/state services
4. coordination and replication
5. installation/runtime packaging

The Python layer should continue to own:

1. prompting
2. reflection loops
3. memory synthesis
4. evals and repair logic
5. model orchestration experiments

## First Run

Once Rust is installed on the machine:

```bash
cargo run --manifest-path rust/eve-kernel/Cargo.toml -- --project-root "$(pwd)"
```

Then check:

```bash
curl http://127.0.0.1:8788/healthz
curl http://127.0.0.1:8788/v1/status
```

## Why Stdlib Only For Now

Using only the Rust standard library keeps this first step easy to read and easy to replace. Once the kernel surface stabilizes, it will make sense to move to a fuller stack with stronger HTTP, structured JSON, tracing, and config support.
