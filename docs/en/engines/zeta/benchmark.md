---
title: Benchmark
---

# Zeta Benchmark

## Why Benchmarks Are Needed

Performance changes are difficult to evaluate from a single execution. JVM warmup, JIT
compilation, garbage collection, host load, and CPU differences can all move the result even when
the code is unchanged. A useful benchmark must therefore fix the workload and runtime resources,
repeat measurements in independent JVMs, preserve raw samples, and compare changes under the same
conditions.

The `seatunnel-benchmarks` module provides two complementary levels of evidence:

- JMH microbenchmarks isolate hot paths such as `SeaTunnelRow` operations.
- Zeta pipeline benchmarks start an embedded single-node cluster and measure complete bounded jobs:

```text
BenchmarkSource -> BenchmarkSink
BenchmarkSource -> BenchmarkTransform -> BenchmarkSink
```

The pipeline Source follows an absolute open-loop schedule. If Zeta falls behind, the waiting time
remains visible in event-time latency instead of being hidden by backpressure. These benchmarks are
intended to detect changes and explain their cost; one run on an arbitrary machine is not a universal
performance claim.

## Run the Benchmarks

Build the benchmark runner together with the current in-repository engine code:

```bash
./mvnw -Pbenchmark -pl seatunnel-benchmarks -am -DskipTests package
```

List the available cases:

```bash
java -jar seatunnel-benchmarks/target/benchmarks.jar -l
```

Run the `SeaTunnelRow` microbenchmarks and save JMH JSON:

```bash
java -jar seatunnel-benchmarks/target/benchmarks.jar SeaTunnelRowBenchmark \
  -rf json \
  -rff seatunnel-benchmarks/target/seatunnel-row-result.json
```

Run both Zeta pipeline cases:

```bash
java -jar seatunnel-benchmarks/target/benchmarks.jar SeaTunnelPipelineBenchmark
```

Run one pipeline and one payload size with custom load parameters:

```bash
java -jar seatunnel-benchmarks/target/benchmarks.jar \
  'SeaTunnelPipelineBenchmark.sourceTransformSink' \
  -p offeredRatePerSecond=300000 \
  -p parallelism=4 \
  -p payloadSize=256 \
  -p transformOperations=64 \
  -rf json \
  -rff seatunnel-benchmarks/target/zeta-pipeline-result.json
```

By default the pipeline benchmark uses a 4 GiB heap, 4 JVM-visible processors, G1, 12 Zeta slots,
parallelism 4, 1,000,000 rows per invocation, and an offered rate of 250,000 rows/s. The default
payload matrix is 64, 128, 256, and 512 characters. These limits are applied to the forked benchmark
JVM by the benchmark class; no additional workflow-level JVM options are required.

For a quick functional smoke test, JMH options such as `-f 1 -wi 0 -i 1 -r 1s` can shorten the run.
Do not use such a single, un-warmed sample for a performance conclusion.

## Read and Visualize the Results

### JMH result

A typical JMH row contains `Mode`, `Cnt`, `Score`, `Error`, and `Units`:

- `Mode` states whether the result is throughput, average time, or another JMH measurement mode.
- `Cnt` is the number of aggregated measurement samples, not the number of processed records.
- `Score` is the estimated result for the benchmark and parameter combination.
- `Error` is JMH's uncertainty estimate for samples inside this run. It does not include performance
  differences between separate GitHub-hosted runner machines.
- `Units` defines the score scale and its direction. For throughput, larger is better; for time per
  operation, smaller is better.

`SeaTunnelPipelineBenchmark` declares 1,000,000 logical operations per invocation. Therefore a JMH
score of `164 ops/ms` means approximately 164,000 processed rows/s. The JMH timer covers submission,
scheduling, and completion of the whole job; it should not be compared directly with a Sink-only
receive-rate metric.

To visualize JMH output:

1. Produce a JSON result with `-rf json -rff <file>` as shown above.
2. Open [JMH Visualizer](https://jmh.morethan.io/).
3. Load the JSON file and compare benchmark names, parameters, scores, errors, forks, and iterations.

The visualizer accepts standard JMH JSON. The custom pipeline summary files described below are not
JMH JSON and should be inspected directly or through the GitHub Actions report artifact.

### Pipeline result

Each pipeline invocation also writes a JSON summary under
`seatunnel-benchmarks/target/pipeline-results`. The most important fields are:

| Field | Meaning |
| --- | --- |
| `processed_rows` / `expected_rows` | The run is valid only when the values are equal. |
| `throughput_rows_per_second` | Completed rows divided by the first-to-last Sink receive interval. |
| `event_time_latency_p50_ms` | Median Sink receive time minus the Source's scheduled generation time. |
| `event_time_latency_p95_ms` / `event_time_latency_p99_ms` | Tail latency, including backlog when the engine falls behind. |
| `first_half_p99_ms` / `second_half_p99_ms` | Whether tail latency grows from the first half of the run to the second. |
| `checksum` | Zero for the direct pipeline and non-zero for the Transform pipeline, proving that transform work reached the Sink. |
| `sustainable` | A configured guardrail requiring complete output, bounded P99, and bounded latency growth. |

The JMH score answers how fast the complete job invocation finished. The pipeline throughput answers
how fast the Sink received records after data started arriving. Event-time latency answers how long a
record waited from its scheduled generation time until the Sink received it. Keep these boundaries
separate when interpreting a result.

To estimate sustainable throughput, repeat the experiment at fixed offered rates on the same idle
machine. Start above the expected capacity and lower the rate until P99 latency and backlog no longer
grow during the run. Compare all independent samples and never select only the best result. GitHub-
hosted runners are suitable for smoke tests and coarse trends, but their changing host CPUs make a
single run unsuitable as a precise regression gate.

## References

1. Andy Georges, Dries Buytaert, and Lieven Eeckhout,
   [Statistically Rigorous Java Performance Evaluation](https://dri.es/files/oopsla07-georges.pdf),
   OOPSLA 2007.
2. Tomas Kalibera and Richard Jones,
   [Rigorous Benchmarking in Reasonable Time](https://dl.acm.org/doi/10.1145/2491894.2464160),
   ISMM 2013.
3. Jeyhun Karimov et al.,
   [Benchmarking Distributed Stream Data Processing Systems](https://arxiv.org/pdf/1802.08496),
   ICDE 2018.

For a practical explanation of how these papers apply to JMH and stream-processing benchmarks, see
[From Java Microbenchmarks to Stream Processing Systems](https://nzw921rx.github.io/nzw921rx-blog/posts/rigorous-java-stream-benchmarking/).
