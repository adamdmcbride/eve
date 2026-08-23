# Third-Party Notices

Eve's original source is licensed under Apache License 2.0. This file records
the direct Python dependencies declared by the project and the external tools
that the source can integrate with. Dependency licenses apply to those
dependencies; they do not replace Eve's project license.

The versions below are the versions resolved in `uv.lock` and reviewed on
2026-08-23. The lock file remains the authority for the exact install graph.

## Declared direct dependencies

| Dependency | Locked version | Install group | License reviewed |
| --- | ---: | --- | --- |
| py-trees | 2.4.0 | core | BSD 3-Clause |
| pytest | 9.0.3 | dev | MIT |
| Dagster | 1.13.19 | infra | Apache-2.0 |
| OpenTelemetry API | 1.44.0 | infra | Apache-2.0 |
| OpenTelemetry SDK | 1.44.0 | infra | Apache-2.0 |
| huggingface-hub | 1.28.0 | techlab | Apache-2.0 |
| LanceDB | 0.37.1 | techlab | Apache-2.0 |
| MLX | 0.32.1 | techlab, Apple silicon only | MIT |
| MLX LM | 0.31.3 | techlab, Apple silicon only | MIT |
| NumPy | 2.5.2 | techlab | BSD-3-Clause, 0BSD, MIT, Zlib, and CC0-1.0 components |
| PyArrow | 25.0.1 | techlab | Apache-2.0 |
| Transformers | 5.15.1 | techlab | Apache-2.0 |
| DeepEval | 4.1.10 | oss-lab | Apache-2.0 |
| Langfuse | 4.14.4 | oss-lab | MIT |
| LangGraph | 1.2.11 | oss-lab | MIT |
| OpenInference Semantic Conventions | 0.1.32 | oss-lab | Apache-2.0 |
| PEFT | 0.20.0 | oss-lab | Apache-2.0 |

Package metadata and license texts are available from each package's official
[PyPI project page](https://pypi.org/). LanceDB's Apache-2.0 text was verified
inside its checksum-matched 0.37.1 wheel; py-trees' BSD text was verified in its
checksum-matched 2.4.0 source distribution.

## Intentionally not installed by Eve

The source can detect or interoperate with tools that are not part of Eve's
declared installation. In particular:

- `mlx-embeddings` 0.1.0 declares GNU GPL v3 in its source distribution.
- `arize-phoenix` 14.6.0 ships under Elastic License 2.0, a source-available
  license rather than an OSI-approved open-source license.
- DVC and Ragas are not declared by the public `oss-lab` extra while their
  resolved dependency paths have open advisories without patched releases.

Eve therefore does not install these packages through a public project extra.
Any local integration remains opt-in, separately installed, and governed by
that project's own license and security posture. Optional probe/adaptor code is
not proof that a package is installed or distributed with Eve.

## External runtimes, models, and services

Eve does not distribute llama.cpp, model weights, OpenClaw, Hermes, hosted
providers, or Apple SDK/runtime components. Installation and integration code
must not imply that those components share Eve's license. Review the exact
upstream version, model card, acceptable-use terms, and data boundary before
enabling one.

## Transitive dependencies

Optional installation groups resolve additional transitive packages in
`uv.lock`. Automated dependency review and SBOM/license generation are release
gates; this human-readable inventory is not a substitute for the license text
shipped by each dependency.
