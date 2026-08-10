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

package org.apache.seatunnel.connectors.seatunnel.influxdb.sink;

import org.apache.seatunnel.api.sink.SinkWriter;
import org.apache.seatunnel.api.table.type.BasicType;
import org.apache.seatunnel.api.table.type.SeaTunnelDataType;
import org.apache.seatunnel.api.table.type.SeaTunnelRowType;
import org.apache.seatunnel.common.utils.function.RunnableWithException;
import org.apache.seatunnel.connectors.seatunnel.influxdb.client.InfluxDBClient;
import org.apache.seatunnel.connectors.seatunnel.influxdb.config.SinkConfig;
import org.apache.seatunnel.connectors.seatunnel.influxdb.config.TimePrecision;

import org.influxdb.InfluxDB;
import org.influxdb.dto.BatchPoints;
import org.influxdb.dto.Point;
import org.influxdb.dto.Pong;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.MockedStatic;
import org.mockito.Mockito;

import java.util.Collections;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InfluxDBSinkWriterTest {

    @Test
    void shouldRegisterAndExecuteTimerFlush() throws Exception {
        SinkWriter.Context context = mock(SinkWriter.Context.class);
        SinkConfig sinkConfig = mock(SinkConfig.class);
        InfluxDB influxDB = mock(InfluxDB.class);
        Pong pong = mock(Pong.class);
        ArgumentCaptor<RunnableWithException> actionCaptor =
                ArgumentCaptor.forClass(RunnableWithException.class);
        SeaTunnelRowType rowType =
                new SeaTunnelRowType(
                        new String[] {"value"}, new SeaTunnelDataType<?>[] {BasicType.INT_TYPE});

        when(sinkConfig.getPrecision()).thenReturn(TimePrecision.MS);
        when(sinkConfig.getKeyTags()).thenReturn(Collections.emptyList());
        when(sinkConfig.getMeasurement()).thenReturn("timer_flush");
        when(sinkConfig.getBatchSize()).thenReturn(100);
        when(sinkConfig.getDatabase()).thenReturn("test");
        when(influxDB.version()).thenReturn("1.8");
        when(influxDB.ping()).thenReturn(pong);
        when(pong.isGood()).thenReturn(true);

        try (MockedStatic<InfluxDBClient> client = Mockito.mockStatic(InfluxDBClient.class)) {
            client.when(() -> InfluxDBClient.getWriteClient(sinkConfig)).thenReturn(influxDB);
            InfluxDBSinkWriter writer = new InfluxDBSinkWriter(sinkConfig, rowType, context);
            writer.write(Point.measurement("timer_flush").addField("value", 1).build());

            verify(context, times(1)).registerFlushAction(actionCaptor.capture());
            verify(influxDB, never()).write(Mockito.any(BatchPoints.class));

            actionCaptor.getValue().run();

            verify(influxDB, times(1)).write(Mockito.any(BatchPoints.class));
        }
    }
}
