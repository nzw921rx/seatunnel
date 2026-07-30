# SeaTunnel Benchmarks

This module contains isolated micro benchmarks for Apache SeaTunnel.

The benchmark module is intentionally excluded from the default Maven reactor. It is only enabled
through the `benchmark` profile, so benchmark-only dependencies such as JMH do not affect
SeaTunnel's normal build, release, or runtime classpath.

## Run benchmarks

Build the benchmark module and its dependencies:

```bash
./mvnw -Pbenchmark -pl seatunnel-benchmarks -am -DskipTests package
```

Run all benchmarks:

```bash
./mvnw -Pbenchmark -pl seatunnel-benchmarks -am -DskipTests package exec:exec
```

Run a specific benchmark:

```bash
./mvnw -Pbenchmark -pl seatunnel-benchmarks -am -DskipTests package exec:exec \
  -Dbenchmarks=SeaTunnelRowBenchmark
```

Run the shaded benchmark jar directly:

```bash
java -jar seatunnel-benchmarks/target/benchmarks.jar SeaTunnelRowBenchmark
```

Write JSON results:

```bash
java -jar seatunnel-benchmarks/target/benchmarks.jar SeaTunnelRowBenchmark \
  -rf json \
  -rff seatunnel-benchmarks/target/benchmark-result.json
```

## IntelliJ IDEA

The benchmark module is behind the inactive `benchmark` Maven profile, so IDEA may not import it
automatically after opening the SeaTunnel root project.

To make IDEA recognize the module:

1. Open the Maven tool window.
2. Expand `Profiles`.
3. Enable the `benchmark` profile.
4. Click `Reload All Maven Projects`.

If the module is still not shown, right-click `seatunnel-benchmarks/pom.xml` and choose
`Add as Maven Project`, then reload Maven once more.

## Interpreting results

Benchmark results are sensitive to machine load, JVM warmup, CPU frequency, and runner type. Prefer
comparing repeated baseline/change runs on the same machine instead of comparing absolute numbers
from different machines.

## Adding benchmarks

Keep benchmark cases small and focused. Good first targets are hot paths that can run on a single
machine without external services, such as:

- `SeaTunnelRow` operations
- format parsing and serialization
- transform hot paths
- connector option parsing
- split generation logic

Common JMH settings should live in `AbstractBenchmark`. Individual benchmark classes should extend
it and only define their own data setup and benchmark methods.
