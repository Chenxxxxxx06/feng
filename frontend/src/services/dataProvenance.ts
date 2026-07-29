export type DataSourceType = 'historical' | 'simulated' | 'demo';

export interface DataTimeRange {
  start?: string | null;
  end?: string | null;
}

export interface DataProvenance {
  source_type: DataSourceType;
  data_time_range: DataTimeRange;
  is_demo: boolean;
  source_label: string;
  source_description: string;
}
