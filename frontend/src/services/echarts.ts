import { BarChart, GraphChart, LineChart } from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components';
import { use } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';

// Register only the chart families used by the application. Importing the
// top-level `echarts` package pulled every renderer and chart into all routes.
use([
  BarChart,
  GraphChart,
  LineChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export { graphic, init } from 'echarts/core';
export type { ECharts, EChartsCoreOption as EChartsOption } from 'echarts/core';
