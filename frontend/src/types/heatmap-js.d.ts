// Hand-written types for heatmap.js 2.0.5 (https://www.patrick-wied.at/static/heatmapjs/).
// The package ships no types of its own.
//
// These MUST mirror `Heatmap.prototype` in build/heatmap.js exactly. An earlier
// version of this file declared a `remove()` method that the library does not
// have; because the declaration compiled, every call site type-checked and then
// threw `TypeError: instance.remove is not a function` at runtime the moment the
// dashboard tore an overlay down. Do not add a method here without finding it on
// `Heatmap.prototype` first.
//
// There is deliberately no destroy/remove: heatmap.js appends its canvas to the
// container and never offers to take it back. Callers tear an instance down by
// emptying the container element themselves.
declare module "heatmap.js" {
  export interface HeatmapGradient {
    [stop: string]: string;
  }

  export interface HeatmapConfig {
    container: HTMLElement;
    /** Point radius in px. Overridden per-point by `HeatmapDataPoint.radius`. */
    radius?: number;
    maxOpacity?: number;
    minOpacity?: number;
    opacity?: number;
    /** 0..1 — higher is softer. */
    blur?: number;
    gradient?: HeatmapGradient;
    backgroundColor?: string;
    useGradientOpacity?: boolean;
    /** Field names heatmap.js reads off each data point. */
    xField?: string;
    yField?: string;
    valueField?: string;
  }

  export interface HeatmapDataPoint {
    x: number;
    y: number;
    value: number;
    radius?: number;
  }

  export interface HeatmapData {
    max?: number;
    min?: number;
    data: HeatmapDataPoint[];
  }

  export interface HeatmapInstance {
    addData(data: HeatmapDataPoint | HeatmapDataPoint[]): HeatmapInstance;
    removeData(data?: HeatmapDataPoint | HeatmapDataPoint[]): HeatmapInstance;
    setData(data: HeatmapData): HeatmapInstance;
    setDataMax(max: number): HeatmapInstance;
    setDataMin(min: number): HeatmapInstance;
    configure(config: Partial<HeatmapConfig>): HeatmapInstance;
    repaint(): HeatmapInstance;
    getData(): Required<HeatmapData>;
    getDataURL(): string;
    getValueAt(point: { x: number; y: number }): number | null;
  }

  export function create(config: HeatmapConfig): HeatmapInstance;
  export function register(pluginKey: string, plugin: unknown): void;

  const h337: { create: typeof create; register: typeof register };
  export default h337;
}
