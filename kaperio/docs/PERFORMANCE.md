# Performance Evidence

Date: 2026-09-25. These are local observations, not an independent benchmark or
a guarantee of the fastest settings on every machine. Only synthetic documents
and candidates were used. No original user document, password, or extracted hash
is present in these reports.

## Engine and machine

- Official latest stable checked on 2026-09-25: Hashcat 7.1.2, released 2025-08-23.
  [Upstream release](https://github.com/hashcat/hashcat/releases/tag/v7.1.2).
- The local upstream archive matches its official SHA-256, recorded in DESKTOP.md.
- Windows 11, RTX 4060 Laptop GPU, NVIDIA driver 596.49, device 1, OpenCL fallback.
- CUDA RTC is not installed. Driver thermal-throttling and unsupported fan-read
  warnings were retained; protection was not disabled. Workload 1, abort at 80 C.
- Highest reported temperature in the matched-mask runs: 70 C.
- Same candidate sets and bounded runs. The upstream kernels are unmodified.

## Accepted improvement

PDF R6 (mode 10700), 100,000 ten-byte dictionary words, all outside the known
synthetic password. Both configurations finished exhausted, using the same list.
Each configuration ran three times in alternating order. Wall time includes
initialization, input writing and process cleanup.

| Policy | Individual seconds | Median seconds |
|---|---|---:|
| Previous dictionary policy, pure kernel | 16.907, 16.516, 16.157 | 16.516 |
| New bounded auto policy, optimized kernel | 6.406, 6.406, 5.532 | 6.406 |

Observed completion speedup: **2.58x for this workload**. This applies upstream
Hashcat `-O` where candidate lengths permit it; the same optimization is available
to a correctly configured Hashcat CLI. It is not an improvement over that CLI.
Longer candidate lists retain the pure kernel, rather than silently dropping words.

Reproduce with `tests/dictionary_benchmark.py --hashcat PATH`.
Raw results: [dictionary-20260925.json](dictionary-20260925.json).

## Matched CLI comparison

Three profiles, three repetitions each, rotated order, four modes, 36 completed
runs. Each run sampled 8 seconds after its first nonzero speed, discarding the
first 3 seconds. Eight lowercase characters, 208,827,064,576 possible candidates.
CLI arguments were independently assembled and asserted equal to Kaperio's.
These figures are medians of each run's median reported speed, in hashes/second.

| Mode | CLI pure | CLI auto | Kaperio auto |
|---|---:|---:|---:|
| 10400, PDF RC4-40 | 486,831,765 | 407,701,138 | 502,880,275 |
| 10700, PDF R6 AES-256 | 9,179 | 58,611 | 58,698 |
| 9600, Office 2013 | 9,018 | 8,551 | 9,069 |
| 13600, WinZip AES | 611,632 | 623,557 | 608,732 |

PDF R6 benefits from the upstream optimized kernel; wrapper and identically
configured CLI are approximately equal in this observation. There is no accepted
improvement for the other modes. Office/ZIP pure/auto profiles have identical
kernel arguments and therefore expose run-to-run variability, not algorithm gains.
In particular the PDF RC4-40 variation must NOT be reported as Kaperio beating
Hashcat, nor as proof of the best kernel for that device.

Limitations: short samples, one laptop, driver clock/thermal behavior, no controlled
ambient or power-state experiment, and some concurrent CPU-only QA. No confidence
interval, universal overhead bound, CUDA comparison, macOS/Linux GPU comparison,
real-world password recovery probability, or exhaustive workload/device search is
established. Hashcat still autotunes each run. The earlier interrupted measurement
set is excluded. Raw results: [mask-20260925.json](mask-20260925.json).

Reproduce by generating fixtures with `tests/integration.py`, then running
`tests/benchmark.py --hashcat PATH --zip2john PATH --seconds 8 --output NEW_DIRECTORY`.

## Correctness gates

The original nine format recovery cases passed after renaming and kernel-policy
changes. Eight additional GPU cases passed: 16-byte and 17-byte boundaries,
18-byte Japanese words, and literal `$HEX[...]` words, for PDF RC4-40 and PDF R6.
New methods have separate end-to-end tests in `tests/strategy_integration.py`.
Unit tests also include transformed/combined-length bounds so fast kernels cannot
be selected using only the unmodified base-word length.

## 0.3 mixed-length policy and negative evidence

Same RTX 4060 Laptop/OpenCL/Hashcat 7.1.2, workload 1, 80 C stop. Latest official
release was checked again on 2026-09-25. No competing GPU job or CPU test suite ran
during these trials. Editing/docs/network orchestration continued. Clocks and room
temperature were not controlled; driver throttling warnings remained. These are
single-machine observations, not universal speedups or superiority to a manually
partitioned upstream Hashcat job.

With 99,999 ten-byte synthetic words and one 18-byte word, PDF R6 full exhaustion
took 17.422 / 17.297 / 17.343 seconds with the previous whole-list policy, versus
10.531 / 10.578 / 10.609 seconds with short/long stages. Alternating three repeats
gave medians **17.343 vs 10.578 seconds (1.64x)**. Every candidate is retained.
The long candidate was also made the actual password in a separate recovery test
and was found after the short stage completed. This is a different workload from
the earlier short-only 2.58x result; the two speedup factors must not be multiplied.

The split policy was also tested at two lower sizes, with two order-reversed runs
per policy. Each list contained the short words below plus one long word:

| Short words | Previous median seconds | Forced split median seconds |
|---|---:|---:|
| 32,768 | 9.2735 | 9.4845 |
| 65,536 | 12.3910 | 10.0625 |

**No improvement was accepted at 32,768.** The shipping threshold was raised to
65,536 base words, only for PDF R6, with tiny lists and other modes left unsplit.
This is a conservative local heuristic, not a globally optimal crossover. The
threshold test deliberately forces 32,768 for comparison even after this change.

Guided recovery passed on synthetic PDF RC4-40, PDF R6, Office DOCX and WinZip AES.
A completed-stage pause/resume recovered the same result without repeating the
completed stage. These fixtures establish functionality, not a real-world recovery
percentage or evidence that the heuristic order is statistically optimal.

Workload measurement ran 1,2,3,3,2,1. Higher workload reported higher raw throughput,
but driver temperature-control warnings invalidated every trial. The tuner correctly
**retained workload 1**; no tuning speedup is claimed. The final telemetry gate also
requires temperature availability for every active device. CUDA runtime comparison,
driver changes, cross-job hardware profiles and physical Mac/Linux GPU measurements
remain unperformed. Repeated tests/candidates in calibration consume real time.

Reproduce: `tests/planning_integration.py --hashcat PATH --zip2john PATH --benchmark --tune`
and `tests/split_benchmark.py --hashcat PATH`. Raw synthetic results:
[planning and mixed list](planning-20260925.json),
[split threshold](split-threshold-20260925.json).
