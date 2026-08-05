---
title: 基准测试
---

# Zeta 基准测试

## 为什么需要基准测试

单次运行很难说明代码的真实性能。JVM 预热、JIT 编译、垃圾回收、宿主机负载和 CPU
型号都会让同一份代码得到不同结果。因此，有效的基准测试需要固定负载与运行资源，在多个
独立 JVM 中重复测量，保留原始样本，并在相同条件下比较变更。

`seatunnel-benchmarks` 模块提供两种互补的性能证据：

- JMH 微基准用于隔离 `SeaTunnelRow` 等热点路径。
- Zeta 完整链路基准会启动单节点嵌入式集群，并执行两种有界作业：

```text
BenchmarkSource -> BenchmarkSink
BenchmarkSource -> BenchmarkTransform -> BenchmarkSink
```

Pipeline Source 使用绝对时间的开环调度。当 Zeta 跟不上输入速率时，等待时间仍会体现在
event-time latency 中，不会被背压隐藏。这些基准用于发现性能变化并解释成本；任意机器上的
一次运行不能代表通用性能结论。

## 如何运行

构建 benchmark runner 以及当前仓库中的引擎代码：

```bash
./mvnw -Pbenchmark -pl seatunnel-benchmarks -am -DskipTests package
```

查看所有可运行场景：

```bash
java -jar seatunnel-benchmarks/target/benchmarks.jar -l
```

运行 `SeaTunnelRow` 微基准并保存 JMH JSON：

```bash
java -jar seatunnel-benchmarks/target/benchmarks.jar SeaTunnelRowBenchmark \
  -rf json \
  -rff seatunnel-benchmarks/target/seatunnel-row-result.json
```

运行两条 Zeta 完整链路：

```bash
java -jar seatunnel-benchmarks/target/benchmarks.jar SeaTunnelPipelineBenchmark
```

指定一条链路、一个 payload 大小以及负载参数：

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

Pipeline benchmark 默认使用 4 GiB 堆内存、4 个 JVM 可见处理器、G1、12 个 Zeta slot、
并行度 4、每次 invocation 处理 1,000,000 行，输入速率为 250,000 行/秒。默认 payload
矩阵为 64、128、256 和 512 个字符。这些资源限制由 benchmark 类传给 fork JVM，
workflow 不需要重复设置 JVM 参数。

功能冒烟时，可以使用 `-f 1 -wi 0 -i 1 -r 1s` 等 JMH 参数缩短运行时间。但这种没有预热、
只有一个样本的结果不能用于性能结论。

## 怎么看指标和可视化

### JMH 指标

典型 JMH 结果包含 `Mode`、`Cnt`、`Score`、`Error` 和 `Units`：

- `Mode` 表示吞吐、平均耗时或其他 JMH 测量模式。
- `Cnt` 是参与聚合的 measurement 样本数，不是处理行数。
- `Score` 是当前 benchmark 与参数组合的估计结果。
- `Error` 是 JMH 对本次运行内部样本给出的不确定性估计，不包含不同 GitHub-hosted
  Runner 宿主机之间的性能差异。
- `Units` 决定 Score 的量纲和方向。吞吐越大越好，每次操作耗时越小越好。

`SeaTunnelPipelineBenchmark` 声明每个 invocation 包含 1,000,000 个逻辑操作。因此
`164 ops/ms` 约等于每秒处理 164,000 行。JMH 计时覆盖作业提交、调度和整条链路完成，
不能直接与只统计 Sink 接收区间的吞吐指标比较。

JMH 结果可以这样可视化：

1. 按上面的命令使用 `-rf json -rff <file>` 生成 JSON。
2. 打开 [JMH Visualizer](https://jmh.morethan.io/)。
3. 加载 JSON，按 benchmark 名称与参数查看 Score、Error、fork 和 iteration。

Visualizer 接收标准 JMH JSON。下面的 pipeline summary 是自定义 JSON，需要直接查看，
或者使用 GitHub Actions 生成的报告产物。

### Pipeline 指标

每次 pipeline invocation 还会在 `seatunnel-benchmarks/target/pipeline-results` 中写入一份
JSON 汇总。主要字段如下：

| 字段 | 含义 |
| --- | --- |
| `processed_rows` / `expected_rows` | 两者相等时本次运行才有效。 |
| `throughput_rows_per_second` | Sink 从第一条到最后一条记录接收区间内的完成速率。 |
| `event_time_latency_p50_ms` | Sink 接收时间减去 Source 计划生成时间的中位数。 |
| `event_time_latency_p95_ms` / `event_time_latency_p99_ms` | 尾延迟；引擎跟不上时包含积压等待。 |
| `first_half_p99_ms` / `second_half_p99_ms` | 判断尾延迟是否从前半段持续增长到后半段。 |
| `checksum` | 直连链路为 0；Transform 链路非 0，用于证明 Transform 工作到达 Sink。 |
| `sustainable` | 配置的保护条件，要求输出完整、P99 受控且延迟增长受控。 |

JMH Score 回答整次作业 invocation 完成得多快；pipeline throughput 回答数据开始到达后 Sink
接收得多快；event-time latency 回答记录从计划生成到 Sink 接收等待了多久。解释结果时必须
区分这些测量边界。

估算可持续吞吐时，应在同一台空闲机器上按固定输入速率重复测试。先从明显高于预期容量的
速率开始，再逐步降低，直到 P99 和 backlog 不再随运行持续增长。应比较全部独立样本，不能
只选择最好的一次。GitHub-hosted Runner 适合功能冒烟和粗粒度趋势，但宿主 CPU 会变化，
不应根据单次运行建立精细的性能回归门禁。

## 参考资料

1. Andy Georges、Dries Buytaert、Lieven Eeckhout，
   [Statistically Rigorous Java Performance Evaluation](https://dri.es/files/oopsla07-georges.pdf)，
   OOPSLA 2007。
2. Tomas Kalibera、Richard Jones，
   [Rigorous Benchmarking in Reasonable Time](https://dl.acm.org/doi/10.1145/2491894.2464160)，
   ISMM 2013。
3. Jeyhun Karimov 等，
   [Benchmarking Distributed Stream Data Processing Systems](https://arxiv.org/pdf/1802.08496)，
   ICDE 2018。

关于这些论文如何应用到 JMH 与流处理基准测试，可继续阅读：
[从 Java 微基准到流处理系统：三篇性能评估论文精读与 JMH 实战](https://nzw921rx.github.io/nzw921rx-blog/posts/rigorous-java-stream-benchmarking/)。
