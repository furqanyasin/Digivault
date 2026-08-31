declare module "heatmap.js" {
  export interface HeatmapConfig {
    container: HTMLElement;
    radius?: number;
    maxOpacity?: number;
    minOpacity?: number;
    blur?: number;
    gradient?: Record<string, string>;
  }

  export interface HeatmapDataPoint {
    x: number;
    y: number;
    value: number;
    radius?: number;
  }

  export interface HeatmapInstance {
    setData(data: { max?: number; min?: number; data: HeatmapDataPoint[] }): void;
    addData(data: HeatmapDataPoint | HeatmapDataPoint[]): void;
    repaint(): void;
    getData(): { max: number; min: number; data: HeatmapDataPoint[] };
    remove(): void;
  }

  export function create(config: HeatmapConfig): HeatmapInstance;
  const h337: { create: typeof create };
  export default h337;
}
