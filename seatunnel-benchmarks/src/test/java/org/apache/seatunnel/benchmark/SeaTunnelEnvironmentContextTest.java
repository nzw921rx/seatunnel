/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.seatunnel.benchmark;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;

class SeaTunnelEnvironmentContextTest {

    @TempDir Path resultDirectory;

    @Test
    void shouldExecuteBothPipelinesOnEmbeddedZeta() throws Exception {
        String property = SeaTunnelEnvironmentContext.RESULT_DIRECTORY_PROPERTY;
        String previousResultDirectory = System.getProperty(property);
        System.setProperty(property, resultDirectory.toString());
        SeaTunnelEnvironmentContext context = new SeaTunnelEnvironmentContext();
        try {
            context.setUp();
            PipelineBenchmarkOptions options = new PipelineBenchmarkOptions(2_000L, 0L, 1, 32, 4);

            BenchmarkRunResult direct = context.execute(BenchmarkPipeline.SOURCE_SINK, options);
            BenchmarkRunResult transformed =
                    context.execute(BenchmarkPipeline.SOURCE_TRANSFORM_SINK, options);

            assertEquals(2_000L, direct.getProcessedRows());
            assertEquals(0L, direct.getChecksum());
            assertEquals(2_000L, transformed.getProcessedRows());
            assertNotEquals(0L, transformed.getChecksum());
        } finally {
            context.tearDown();
            if (previousResultDirectory == null) {
                System.clearProperty(property);
            } else {
                System.setProperty(property, previousResultDirectory);
            }
        }
    }
}
