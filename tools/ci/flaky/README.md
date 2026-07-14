<!--
Licensed to the Apache Software Foundation (ASF) under one or more
contributor license agreements.  See the NOTICE file distributed with
this work for additional information regarding copyright ownership.
The ASF licenses this file to You under the Apache License, Version 2.0
(the "License"); you may not use this file except in compliance with
the License.  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# SeaTunnel CI Flaky Observatory

This directory contains fork-only tooling for the 30-day CI observatory.

The workflow design keeps observability code in the fork while testing
`apache/seatunnel@dev` in a separate checkout. Each failed observation produces
two stable identifiers:

- `failure_fingerprint_id`: how the run failed.
- `pr_fingerprint_id`: the PR shape that tends to trigger the failure.

The fixed tracking issue title is:

`[CI][Flaky] 30-day dev branch and PR CI observatory`

GitHub only runs scheduled workflows from a repository's default branch. Push
this work to the fork and either make `ci/flaky-observatory` the fork default
branch for the 30-day window, or merge these fork-only workflow files into the
fork default branch.

Local dry-run example:

```bash
python3 tools/ci/flaky/flaky_observatory.py collect \
  --workspace . \
  --output /tmp/seatunnel-flaky.jsonl \
  --exit-code 1 \
  --workflow local \
  --job local-smoke \
  --run-url local

python3 tools/ci/flaky/flaky_observatory.py update-issue \
  --records /tmp/seatunnel-flaky.jsonl \
  --repository nzw921rx/seatunnel \
  --dry-run
```
